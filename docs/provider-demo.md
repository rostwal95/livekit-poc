# Provider inference demo operations

Status: Active
Last reviewed: 10 November 2026

## Scope and current evidence

provider_real is an explicit native LiveKit pipeline using Deepgram recognition,
OpenAI reasoning/tool selection and ElevenLabs generated speech. The application,
LiveKit media server, case authority, durable worker, console and tracing run on
the local Docker stack; inference requests use the configured external providers.
This is an opt-in provider demonstration for the local POC.
No GitHub publishing, hosted CI, Cloud deployment or carrier account is required.

The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping source
plays the unchanged WAV from sample zero. Closed, muted, replaced, superseded or
not-ready input cannot be restarted by a late reply. Physical microphone capture
is independent; fixture alignment does not force a model tool or establish ASR quality. The
[provider work item](work-items/0018-p1-provider-demo.md) owns observed outcomes.
A configured badge, nonempty key, healthy process or emitted token count alone is
insufficient. complete P2/P3 acceptance remains pending, and this guide does not certify model accuracy,
physical microphone capture, human hearing or production capacity.

| Native profile | Inference | Explicit preparation |
| --- | --- | --- |
| scripted, default | Deterministic local speech/model fixtures | Ordinary business setup; no provider keys or weights |
| local_real | Local Whisper/Qwen/Piper engines | Pinned cache and private engine profile; [separate operations](local-real-inference.md) |
| provider_real | Direct Deepgram/OpenAI/ElevenLabs APIs | Three privately validated keys and declared plugin versions; no local engine/cache prerequisite |

All three use the same bound task, no-argument investigation/inspection/cancellation
tools and separate exact human quote confirmation. No request or model output can
select a profile, credentials, endpoint or business scope. There is no automatic
provider/model fallback.

## Fixed model and transport contract

| Stage | Model and API behavior | Boundary |
| --- | --- | --- |
| ASR | Deepgram nova-3, English; official batch recognition after explicit manual flush | Bounded received PCM; genuine final transcription; no continuous streaming-ASR claim |
| LLM | OpenAI gpt-5.4-mini; streaming Chat Completions; reasoning_effort=none, store=false; at most 128 output tokens | Only the existing three bound tools; model content grants no confirmation authority |
| TTS | ElevenLabs eleven_v4_turbo; public George voice JBFqnCBsd6RMkjVDRZzb; official chunked HTTP output, PCM16 mono24 kHz | Generated speech; no prerecorded output lookup or aligned-transcript claim |

The three LiveKit plugins are pinned to 1.8.11 alongside Agents 1.8.11. GPT-5.4 Mini supports
streaming, function calling and none reasoning, as specified by
[official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
[LiveKit's Deepgram guide](https://docs.livekit.io/agents/models/stt/deepgram/)
distinguishes Nova-3 from Flux's separate turn-taking API. The
[ElevenLabs model catalog](https://elevenlabs.io/docs/overview/models/) lists v4
Turbo and Flash v2.5 as different selections. Provider claims about latency are
not this POC's measured latency or an account-access guarantee.

Manual turn reset can briefly overlap the active recognition handle with its
closing predecessor. The adapter owns at most two handles and releases each only
after successful SDK close. Actual ASR remains bounded to one active and one
waiting operation; audio, session and ten-second operation limits are unchanged.

The pinned SDK filters model-specific constructor parameters. The factory fixes
none reasoning and store=false in the actual outgoing JSON; the final transport
guard and actual tool-bearing wire test require both values.

The frozen [provider workload](../local-setup/workloads/p1-provider-real-v2.json)
owns model/voice, transport, caps, schedule and counts. Changing it requires a new
reviewed declaration before measurement; do not rewrite measured inputs to make
a failed run pass.

## First local workspace

Run from the repository root with the supported Python 3.14 environment, supported
Node runtime, Docker/Compose and Corepack available. The root packageManager pins
pnpm 12.18.0; use Corepack instead of an unrelated global pnpm. Install and build
the frozen development dependencies before runtime:

```sh
make bootstrap
corepack pnpm install --frozen-lockfile
make frontend-check
make browser-setup
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
```

The [persistent workspace procedure](../local-setup/README.md#first-persistent-p1-business-workspace)
owns auxiliary-source backups and retry rules. prepare-business explicitly
activates a separate empty inquiry source and applies the ordered ACTIVE v4
upgrades. It never quiesces the serving M1 SQLite database. Fixture initialization
is separate and retains supplier/receiver identity and existing booking state.
Existing valid ACTIVE v4 targets are read-only checked without restaging current
business work. Conflicting or unowned migration state must be investigated rather
than deleted. Startup performs no schema activation, fixture seed or consent.

## Private credential setup and presence check

```sh
make provider-setup
# Fill the three fields in local-setup/.env.providers using a local editor.
make provider-check
```

The equivalent stack actions are init-providers and check-providers. Setup creates
an ignored owner-only mode 0600 file if absent and preserves an existing valid
file. Exactly DEEPGRAM_API_KEY, OPENAI_API_KEY and ELEVEN_API_KEY are accepted.
Values are literal data, not shell code. Never source the file, use cat/printenv to
share it, put values in argv or paste them into reports. Keep the file owned by
the local user with mode 0600 after editing. Symlinks, hardlinks, duplicate/unknown
fields, unsafe permissions and invalid or missing values fail closed.

provider-check prints only named presence booleans and performs no provider call.
It exits with code 2 while any field is empty. A successful presence check establishes
neither account credit nor model/voice access. Keys stay outside the browser,
control API, durable worker, collector, local model engines and build layers.

## Interactive start and stop

```sh
make provider-start
.venv/bin/python local-setup/stack.py status
.venv/bin/python local-setup/stack.py worker-status
make provider-stop
```

The stack action names are start-provider and stop-provider. Start requires all
three keys, builds the shared runtime, performs read-only ACTIVE v4/same-scope
fixture preflight and then enables the native agent, API, durable worker and
local Jaeger with trusted provider_real mode. Only the native service receives
the three provider credentials. It starts no local model engines and downloads
no weights. Dependency/image preparation may use the network separately from
inference. The retained v2 gate qualified the declared account/model/speech scenario; future
access and operation failures still require fresh setup and actual progress.

Open the loopback console and use the separate local operator token as documented
in the [setup guide](../local-setup/README.md). The model API keys never enter the
console. Resume a case, choose the labelled prerecorded input or explicitly
permission-controlled microphone, and Join. The badge distinguishes configured
from native-profile-matched readiness. It does not certify recognition or playback.
Interrupt and End release media resources without business cancellation. Exact
quote/revision approval remains a separate authenticated workflow action.

Use provider-stop when leaving the provider profile: it requests the existing
35-second native/worker drain, restores ordinary API/scripted mode and removes
the credential-bearing native container. It attempts credential-container removal
even if another shutdown step fails; incomplete cleanup remains a failure. Named
volumes, accepted work and the private credential file remain. Stop does not need
to read provider keys. A destructive reset is not a normal stop or recovery step.

### Joined three-project showcase

The joined P1/P2/P3 showcase has its own explicit provider mode on the host:

```sh
make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-2
```

It reads the same private credential file with the strict loader and passes the
three keys only to each room's native worker process. The worker reuses the
fixed Deepgram nova-3, OpenAI gpt-5.4-mini and ElevenLabs eleven_v4_turbo
adapters above, with a toolless OpenAI plugin because that runtime offers the
model no tools, and the P2 runtime's scheduled-reply timing so durable dispatch
never waits for speech playout. The persisted dispatch decision stays the
deterministic investigation rule; models produce transcripts and replies only.
The browser header shows `LOCAL / REAL PROVIDERS` once the native agent reports
the matching mode. The [0046 work item](work-items/0046-joined-showcase-providers-and-demo.md)
records the selected actual journeys; they are separate from the P1-20 gate.

## Explicit local certificate trust

The default runtime uses the pinned image's OS trust store. A local network may
require an additional approved CA chain already trusted by the host. Select a
public certificate-only PEM bundle explicitly; no certificates are downloaded or
added automatically. Keep private keys and issuer details out of the repository.
The strict reader accepts an absolute regular single-link file owned by the
operator or root, without group/world write access, at most 512 KiB. It rejects
symlinks, private keys, comments, malformed data and non-CA certificates.

```sh
.venv/bin/python local-setup/stack.py start-provider --provider-ca-bundle /absolute/path/approved-ca-bundle.pem
```

The manager atomically retains one public snapshot in ignored generated setup
state and recreates the owned business containers to activate it. Only the native
container mounts that snapshot, read-only at its verified OS CA-file location.
The API and durable worker receive neither a CA mount nor a trust environment
setting. Provider keys remain the same three private fields. Normal startup does
not read ambient CA/proxy settings or activate this option. Stop retains the public
configuration snapshot alongside other generated setup state.

For the registered isolated gate, select the same public trust source explicitly:

```sh
P1_PROVIDER_CA_BUNDLE=/absolute/path/approved-ca-bundle.pem P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

The wrapper binds the selected certificate digest/byte count to fresh runtime
evidence. The helper verifies native readability, actual mounted bytes, the pinned
client's default trust path, hostname checking and CERT_REQUIRED; it also verifies
that the API and worker lack this mount. Only safe numeric/hash metadata is
retained. The run owns a separate snapshot until native container removal is
verified; incomplete cleanup retains it and fails visibly. The recorded input
hash is checked again after media work. Certificate and hostname verification,
fixed provider routes, output caps and deadlines stay enabled.

## Fresh provider acceptance gate

The isolated gate uses its own UUID-labelled API/worker/native/UI, schema, volumes
and synthetic fixtures. It reuses the owned foundation PostgreSQL/LiveKit network
and an owned collector. It does not reset the persistent workspace. Stop the
ordinary conversation worker before running it; use provider-stop if the
interactive provider profile was started:

```sh
make provider-stop
P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

The wrapper defaults to local_real unless the trusted environment explicitly
selects provider_real. P1-20 remains harness mode live in either real profile;
live means actual inference, and does not mean hosted deployment. The direct
source-bound helper is also available:

```sh
.venv/bin/python local-setup/scripts/phase_g_demo.py --mode provider_real --work-seconds 600
```

Prepare the current installed application/console images and host console build,
the explicit three-key file, restricted PostgreSQL roles and the managed
Playwright browser first. The isolated helper prepares only its owned authority
and fixtures; normal persistent activation is separate. Optional --browser-executable
selects an existing absolute executable. Optional --artifact-root must be an
absent absolute child of repository .local/validation. No local cache, inference
network or Whisper/Qwen/Piper container is required for this provider gate.

Two actual browser cases retain the same eight-pending-inquiry cohort, End/fresh
consumer, held PostgreSQL/supplier control and exact human-confirmation assertions.
The work deadline is 600 seconds with 180 seconds reserved for owned cleanup; the
wrapper keeps its original 840-second total deadline under the 900-second catalog
supervisor. Browser interruption stays at most 1.5 seconds, real commit 12 seconds,
other RPCs 8 seconds and browser cleanup 5 seconds. Native ASR/TTS 10-second and
LLM 30-second caps remain finite; no nested automatic retries extend them.

The helper privately validates keys at explicit runtime and writes a temporary
mode 0600 Docker env file only for the UUID-owned native process. It does not copy
values into command arguments or evidence. Fresh evidence must prove nonzero
ASR input/final recognition, LLM input/output usage, generated speech and advancing
browser playback. The wrapper independently revalidates the numeric SDK records,
run-bound browser statistics and sanitized raw OTLP with all three exact
model/provider pairs. Missing setup, 401/429, timeout, missing progress, skips,
stale artifacts or incomplete owned cleanup cannot pass.

### Owned durable-worker checkpoint

The real-media helper sends SIGUSR1 only to its exact UUID-owned running worker,
after installed-source validation. A request flag is not an acknowledgement.
WorkerRuntime reaches its quiescent outer-loop checkpoint only after the child is
reaped, its lease released and post-step queue SQL finished. The helper then uses
installed WorkerHealth.is_quiescent(maximum_age_seconds=10), requires a separate
active=0 durable snapshot, and applies the existing OS pause. Arming, signalling,
health acknowledgement, idle observation and pause share the original 100-second
setup deadline. An active=0 sample alone cannot prove the parent is out of SQL.

Recovery begins its original 45-second clock before unpause, SIGUSR2 and fresh
WorkerHealth.ready acknowledgement. Ready may already report one active child.
This includes resume overhead rather than starting a new window after the reply.
The helper owns possibly lost signal/pause acknowledgements before issuing them;
unresolved resume or cleanup remains non-passing. Resume and close share the
existing 12-second ceiling, without resetting a failed attempt's deadline.
SIGTERM/SIGINT remain sticky shutdown requests; SIGUSR2 cannot reverse shutdown.
No model/provider or browser controls gain maintenance or mutation authority.

The retained proof has an exact nine-field worker_quiescence record: schema,
resumed phase, observed/resolved flags, one quiesce and one resume signal, and
positive health/idle observation counts bounded at 2,001. The independent real
acceptance consumer rejects absent, unknown, coerced, partial or repeated-signal
proof. These setup observations remain distinct from business results and media
qualification.

## Observability, resources and retention

Local evidence observes native/API/worker cgroup CPU and memory windows. External
provider CPU, memory and internal capacity are unobserved; downloaded-model/engine
counters cannot substitute for remote usage. Numeric usage, control timings,
current-task trace correlation and independent supplier/receiver receipts are
separate facts. A response, hint, transcript or playback event is never business
authority or human acknowledgement.

Native logs keep the established five-field finite schema. Prompts, transcripts,
audio bodies, headers, key values, raw provider errors and exception chains are
excluded from retained diagnostics. Trace copies admit fixed model/provider labels;
known upstream display aliases are normalized without changing SDK observations.
Browser trace/video/HAR remain disabled and screenshots require empty passwords.

Content-free local evidence does not establish provider zero data retention.
Deepgram requests opt out of model improvement; OpenAI store=false is not a blanket
retention promise. ElevenLabs logging remains the pinned default true; its
[text-to-dialogue zero-retention option](https://elevenlabs.io/docs/changelog/2026/6/8)
requires enterprise entitlement and is not silently enabled or substituted here.
Use synthetic demonstration data. Do not infer production capacity, model quality
or a cost guarantee from one passing local scenario.

## Nova 2.5 Sonic alternative

Nova 2.5 Sonic is a verified SDK alternative, not this implemented three-stage
profile. AWS documents model ID amazon.nova-2-5-sonic and four supported in-region
locations; [the model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-5-sonic.html)
and [LiveKit integration](https://docs.livekit.io/agents/models/realtime/nova-sonic/)
describe its bidirectional speech-to-speech pipeline. The pinned AWS plugin exposes
with_nova_sonic_2_5 through its realtime extra. That transport requires standard
AWS credentials, including temporary-session credentials when applicable,
according to [AWS API compatibility](https://docs.aws.amazon.com/bedrock/latest/userguide/models-api-compatibility.html).
It is not an interchangeable Bedrock API-key field. Adopting it requires a separate
reviewed runtime, dependency and real-media qualification; the existing strict
three-key provider file does not accept AWS fields.
