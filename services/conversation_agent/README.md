# Native conversation agent

Status: Active
Last reviewed: 11 November 2026

## Overview

A separate LiveKit Agents consumer connects a real native AgentSession to the
P1 durable investigation service. The default scripted profile uses declared
STT/LLM fixtures and prerecorded spoken PCM without downloads or paid inference.
The explicit local_real profile implements prepared local Whisper recognition,
Qwen model/tool selection and generated Piper speech; actual engine/model/media
qualification remains pending. The authenticated workflow panel owns exact
quote approval; the conversation exposes investigation, inspection and explicit
cancellation of its current owned task.

## Implementation status

| Capability | Implemented surface | Evidence boundary |
| --- | --- | --- |
| Native conversation | AgentSession, Agent and three no-argument function tools | Actual SDK text and manually committed audio tests |
| Media readiness | Public RoomIO readiness barrier before greeting/controls; exact native ready attribute | Gated-subscription regression plus actual browser gate |
| Scripted voice | Default non-silent audio maps to declared investigate/status transcripts and fixed spoken replies | Retained Phase G transport/lifecycle proof, not general inference |
| Provider inference | Explicit trusted provider_real selects official Deepgram/OpenAI/ElevenLabs plugins with native-only keys | Implementation/offline checks present; The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping source
plays the unchanged WAV from sample zero. Closed, muted, replaced, superseded or
not-ready input cannot be restarted by a late reply. Physical microphone capture
is independent; fixture alignment does not force a model tool or establish ASR quality. |
| Local real inference | Explicit trusted local_real selects prepared Whisper/Qwen/Piper and bounded fixed private endpoints | Implementation present; actual engine/model/browser qualification pending |
| Trusted business adapter | Signed room/participant grant, frozen principal/request/replay key, bounded storage offload | Composition/service tests and the separate real PostgreSQL lane |
| Session independence | Interruption/closure does not invoke cancellation; accepted work belongs to durable workers | Native lifecycle tests; full stack recovery needs its own gate |
| Observations | Numeric SDK usage/report files, finite JSON logs, sanitized bounded optional OTLP | Local protobuf receiver/outage tests; inspect collector traces separately |
| Browser demonstration | Native PTT controls, transcription streams and authenticated refresh hints | Actual browser run evidence is recorded in the Phase G work item |

Native function tools use the SDK's async-tool lifecycle: an injected RunContext
records a silent pending update before awaiting storage. Speech can be interrupted
while the SDK owns the pending tool and the bounded adapter retains its real
thread/capacity. The final validated receipt produces the deferred result and
refresh hint. Pending is never narrated as accepted work; PostgreSQL remains the
durable authority. No extra model task-cancellation/listing tools are exposed.

After the SDK session starts, the runtime waits at most ten seconds for its public
RoomIO.wait_for_ready barrier. This waits for the expected participant and native
output subscription; microphone publication is not required. Only then are controls
enabled, continuity.session_ready='true' and the configured finite
continuity.inference_mode are published together, and the greeting is queued. The
browser requires that mode to match its authenticated mint plus active SDK state.
Early control/text input is rejected;
startup failure/cancellation stays visible and still receives independent cleanup.
This prevents interrupting an unsubscribed first output from cancelling the frozen
SDK's shared subscription wait and suppressing later speech/transcription.

The SDK RemoteSession host is disabled through session_host=False. Only the owned
bounded lk.chat and three caller-checked RPC routes can drive the session; the
built-in lk.agent.session byte ingress is not installed.

In the default scripted profile, the first qualified audio turn maps to investigate
and later turns to status. Silent input produces no investigation. Text commands
use an explicit allowlist; cancellation requires the declared cancel command.
Those fixture assertions do not qualify human speech or model quality. Local_real
uses actual local recognition/model/generated speech with the same three bound
no-argument tools; a model cannot prepare or approve an exact quote.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the
[shared design](../../Design.md), [local setup](../../local-setup/README.md),
[Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md),
[local-real operations](../../docs/local-real-inference.md) and
[asset manifest](assets/manifest.json). Scope and release criteria remain in
the [P1 charter](../../docs/projects/agent-continuity-scope.md).

## Requirements

Use the frozen root local, agent and inference extras. The composed business
profile supplies
LiveKit credentials, the PostgreSQL runtime role/schema and trusted scope. The
native worker is named local-business-agent, admits one job and serves its internal
health/load surface on port 8082. Diagnostic worker dispatch stays separate.

P1_TRACE_ENDPOINT optionally selects the validated local OTLP endpoint. The owned
exporter ignores OTEL credential/header and proxy environment configuration. The
profile uses synthetic business state and existing authority; it does not install
a schema, initialize consent or accept migration credentials.

P1_CONVERSATION_INFERENCE accepts only scripted (default), local_real or provider_real.
local_real needs the exact prepared cache and private engines; provider_real needs
the separately validated keys. Neither performs implicit model downloads or fallback. Mode is trusted configuration, not a client/tool argument.
The same worker name serves one configured profile. Models/engines receive no
application credentials, and their endpoints publish no host ports.

## Commands

Use the [local setup lifecycle](../../local-setup/README.md) for the composed
profile, preparation, health checks, start and stop. The installed container entry is:

```sh
python -m services.conversation_agent start
```

Run it from the repository root in the prepared environment. Credentials and
signed grants come from the managed profile and HTTP controller.

### Optional provider profile

provider_real composes official Deepgram nova-3 batch recognition at manual flush,
OpenAI gpt-5.4-mini streaming tool selection and ElevenLabs eleven_v4_turbo chunked
HTTP speech. It preserves the same three no-argument tools, manual turns and exact
separate human confirmation. Only this native process receives the three private
keys. It requires no local model cache or engine and never silently substitutes
profiles. Read the [provider operations guide](../../docs/provider-demo.md).
The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

## Validation

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_conversation*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_tracing.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_worker_tracing.py' -v
```

Tests include real native SDK function execution, nonzero AudioInput frames,
manual STT flush, silent rejection, native TTS emission, caller/body/reader limits,
cleanup ordering, spawn importability and safe errors. A controlled native output
subscription fixture verifies that early controls fail before touching interruption,
then actual synchronized STATUS audio/text follows readiness; timeout and
cancellation fixtures cannot claim readiness. OTLP tests bind a local
receiver and decode actual protobuf, including timeout/outage and shutdown races.
Record browser WebRTC playback, independent worker completion and live model
quality as separate observations.

## Next milestone

Preserve the completed Phase G deterministic regression and current H2, installed
host/Linux artifact and selected provider_real v2 media gates. The
[Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
records the qualified local P1 V1 scope. Repeat affected gates after changes;
local_real remains a distinct unqualified option requiring its own declared run.
Physical quality, human acknowledgement and production capacity remain separate.
all 17 P2 and remaining 14 P3 rows remain planned alongside three passing registered P3 lab rows; hosted CI/publication are outside this local POC scope.
