# Provider inference demo operations

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to set up, check, start, stop and freshly qualify the opt-in provider_real inference profile |
| Audience | Engineers who run the provider demonstration on the local stack; coding agents changing provider composition |
| Scope | P1 provider_real native conversation and the joined showcase provider mode; excludes local_real engines, hosted CI and Cloud deployment |
| Owns | Opt-in provider setup/check/start/stop, private credential boundaries, declared pipeline and fresh provider qualification |
| Related | [Local real-inference operations](local-real-inference.md) · [Provider work item](work-items/0018-p1-provider-demo.md) · [Local setup guide](../local-setup/README.md) · [Observability](observability.md) · [Validation plan](validation-plan.md) |

## Scope and current evidence

This guide covers the opt-in provider_real inference profile for the P1 (agent
continuity) native conversation. It explains first workspace setup, the private
credential file, interactive start and stop, the joined showcase provider mode,
optional certificate trust, the fresh acceptance gate, and observability and
retention. It is for engineers who run the provider demonstration on the local
stack.

Contents:

| Section | Covers |
| --- | --- |
| [Commands](#commands) | Every provider command, with the section that explains it |
| [Fixed model and transport contract](#fixed-model-and-transport-contract) | Pipeline stages, plugin versions, settings, workload declaration and prerecorded input |
| [First local workspace](#first-local-workspace) | Prerequisites, bootstrap commands and prepare-business outcomes |
| [Private credential setup and presence check](#private-credential-setup-and-presence-check) | The private key file, its rules and the presence check |
| [Interactive start and stop](#interactive-start-and-stop) | start-provider, console use, failure reporting and provider-stop |
| [Joined three-project showcase](#joined-three-project-showcase) | The joined showcase's explicit provider mode |
| [Explicit local certificate trust](#explicit-local-certificate-trust) | An optional approved CA bundle for the interactive profile and the gate |
| [Fresh provider acceptance gate](#fresh-provider-acceptance-gate) | Isolated P1-20 gate prerequisites, commands, budgets and evidence |
| [Observability, resources and retention](#observability-resources-and-retention) | Local observations, diagnostics and provider data retention |
| [Nova 2.5 Sonic alternative](#nova-25-sonic-alternative) | A verified SDK alternative that is not implemented here |

### What runs where

provider_real is an explicit native LiveKit pipeline. Inference requests use the
configured external providers.

| Component | Runs on |
| --- | --- |
| Deepgram, for recognition | Configured external provider |
| OpenAI, for reasoning and tool selection | Configured external provider |
| ElevenLabs, for generated speech | Configured external provider |
| Application, LiveKit media server, case authority, durable worker, console and tracing | Local Docker stack |

This is an opt-in provider demonstration for the local proof of concept (POC).
No GitHub publishing, hosted continuous integration (CI), Cloud deployment or
carrier account is required.

### Rules that apply throughout

Each rule is repeated where it matters below.

| Rule area | Rule |
| --- | --- |
| Paid calls | Paid provider calls are explicit opt-in |
| Default profiles | The default inference mode is scripted, and the acceptance wrapper defaults to local_real |
| Profile selection | No request or model output can select a profile |
| Provider keys | Only the native provider runtime receives the three provider keys |
| Key isolation | Keys stay outside the browser, control API, durable worker, collector, local model engines and build layers |
| Credential file | Never source `local-setup/.env.providers`, share it with `cat` or `printenv`, put its values in command arguments or paste them into reports |
| Reset | A destructive reset is not a normal stop or recovery step |

### Current evidence

| Capability | Status | Evidence |
| --- | --- | --- |
| Selected provider_real v2 gate | Qualified | Both actual browser cases passed with cleanup; [provider work item](work-items/0018-p1-provider-demo.md) |
| P1 V1 (the fixed first-version scope) for the local POC | Qualified | Qualified using provider_real v2 |
| Complete P2/P3 acceptance | Partial | Remains pending |

- The provider work item owns observed outcomes.
- A configured badge, nonempty key, healthy process or emitted token count alone
  is insufficient.
- This guide does not certify model accuracy, physical microphone capture, human
  hearing or production capacity.

### Inference profiles compared

| Native profile | Inference | Explicit preparation |
| --- | --- | --- |
| scripted, default | Deterministic local speech/model fixtures | Ordinary business setup; no provider keys or weights |
| local_real | Local Whisper/Qwen/Piper engines | Pinned cache and private engine profile; [separate operations](local-real-inference.md) |
| provider_real | Direct Deepgram/OpenAI/ElevenLabs APIs | Three privately validated keys and declared plugin versions; no local engine/cache prerequisite |

All three profiles use the same bound task, the same no-argument investigation,
inspection and cancellation tools, and the same separate exact human quote
confirmation. No request or model output can select a profile, credentials,
endpoint or business scope. There is no automatic provider or model fallback.

## Commands

Run every command from the repository root after the prerequisites in
[First local workspace](#first-local-workspace). The runnable sequences, in
their required order, stay in the linked sections.

| Task | Command | Notes |
| --- | --- | --- |
| Bootstrap and prepare the persistent workspace | `make bootstrap`, then the sequence in [First local workspace](#first-local-workspace) | Run in the listed order |
| Create the private credential file | `make provider-setup` | Stack action `init-providers`; see [credential setup](#private-credential-setup-and-presence-check) |
| Check that every key field is present | `make provider-check` | Stack action `check-providers`; performs no provider call |
| Start the interactive provider profile | `make provider-start` | Stack action `start-provider`; see [Interactive start and stop](#interactive-start-and-stop) |
| Inspect the stack | `.venv/bin/python local-setup/stack.py status` | None |
| Inspect the durable worker | `.venv/bin/python local-setup/stack.py worker-status` | None |
| Stop the interactive provider profile | `make provider-stop` | Stack action `stop-provider` |
| Start the joined showcase in provider mode | `make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-2` | See [Joined three-project showcase](#joined-three-project-showcase) |
| Start with an approved CA bundle | `.venv/bin/python local-setup/stack.py start-provider --provider-ca-bundle /absolute/path/approved-ca-bundle.pem` | See [Explicit local certificate trust](#explicit-local-certificate-trust) |
| Run the fresh provider gate | `P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20` | Run `make provider-stop` first; see [Fresh provider acceptance gate](#fresh-provider-acceptance-gate) |
| Run the gate with an approved CA bundle | `P1_PROVIDER_CA_BUNDLE=/absolute/path/approved-ca-bundle.pem P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20` | Same public trust source as the interactive profile |
| Run the direct source-bound helper | `.venv/bin/python local-setup/scripts/phase_g_demo.py --mode provider_real --work-seconds 600` | Optional `--browser-executable` and `--artifact-root` |

## Fixed model and transport contract

The pipeline has three stages: automatic speech recognition (ASR), a large
language model (LLM) and text-to-speech (TTS). Audio is 16-bit pulse-code
modulation (PCM16).

| Stage | Model and API behavior | Boundary |
| --- | --- | --- |
| ASR | Deepgram nova-3, English; official batch recognition after explicit manual flush | Bounded received PCM; genuine final transcription; no continuous streaming-ASR claim |
| LLM | OpenAI gpt-5.4-mini; streaming Chat Completions; reasoning_effort=none, store=false; at most 128 output tokens | Only the existing three bound tools; model content grants no confirmation authority |
| TTS | ElevenLabs eleven_v4_turbo; public George voice JBFqnCBsd6RMkjVDRZzb; official chunked HTTP output, PCM16 mono 24 kHz | Generated speech; no prerecorded output lookup or aligned-transcript claim |

### Plugin versions and provider references

The three LiveKit plugins are pinned to 1.8.11 alongside Agents 1.8.11.

| Component | Version | Notes |
| --- | --- | --- |
| LiveKit Agents | 1.8.11 | The three plugins are pinned alongside it |
| `livekit-plugins-deepgram` | 1.8.11 | Deepgram nova-3 recognition |
| `livekit-plugins-openai` | 1.8.11 | OpenAI gpt-5.4-mini reasoning and tool selection |
| `livekit-plugins-elevenlabs` | 1.8.11 | ElevenLabs eleven_v4_turbo speech |

| Reference | What it states |
| --- | --- |
| [Official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini) | GPT-5.4 Mini supports streaming, function calling and none reasoning |
| [LiveKit's Deepgram guide](https://docs.livekit.io/agents/models/stt/deepgram/) | Nova-3 is distinct from Flux's separate turn-taking API |
| [ElevenLabs model catalog](https://elevenlabs.io/docs/overview/models/) | v4 Turbo and Flash v2.5 are different selections |

Provider claims about latency are not this POC's measured latency or an
account-access guarantee.

### Recognition handle overlap

Manual turn reset can briefly overlap the active recognition handle with its
closing predecessor. The adapter owns at most two handles and releases each only
after a successful close by the software development kit (SDK). Actual ASR
remains bounded to one active and one waiting operation. Audio, session and
ten-second operation limits are unchanged.

### Reasoning and storage settings

The pinned SDK filters model-specific constructor parameters. The factory fixes
none reasoning and store=false in the actual outgoing JSON. The final transport
guard and the actual tool-bearing wire test require both values.

### Frozen workload declaration

The frozen [provider workload](../local-setup/workloads/p1-provider-real-v2.json)
owns model and voice, transport, caps, schedule and counts. Changing it requires
a new reviewed declaration before measurement. Do not rewrite measured inputs to
make a failed run pass.

### Prerecorded input

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping
source plays the unchanged WAV from sample zero. Closed, muted, replaced,
superseded or not-ready input cannot be restarted by a late reply. Physical
microphone capture is independent. Fixture alignment does not force a model tool
or establish ASR quality.

## First local workspace

All prerequisites are used from the repository root.

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python | 3.14 | The supported environment |
| Node | A supported runtime | None |
| Docker and Compose | Required | None |
| Corepack | pnpm 12.18.0, pinned by the root packageManager | Use Corepack instead of an unrelated global pnpm |

Install and build the frozen development dependencies before runtime, then
prepare the persistent workspace:

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

### What prepare-business does

The [persistent workspace procedure](../local-setup/README.md#first-persistent-p1-business-workspace)
owns auxiliary-source backups and retry rules.

prepare-business is not read-only when the target schema is ACTIVE v4: it runs
the owner-only v5 upgrade. Its report names what happened in its
schemaActivation field:

| Target before preparation | What prepare-business does | `schemaActivation` |
| --- | --- | --- |
| Fresh target | Explicitly activates a separate empty inquiry source, then applies the ordered upgrades through v4 and the additive v5 step | `explicit_empty_bootstrap` |
| Existing valid ACTIVE v4 | Runs the owner-only v5 upgrade without restaging current business work | `owner_upgrade_v5` |
| Existing valid ACTIVE v5 | Checks the target read-only | `read_only_ready` |

- prepare-business never quiesces the serving M1 SQLite database (the original
  confirmed-investigation intake).
- Fixture initialization is separate. It retains supplier and receiver identity
  and existing booking state.
- Conflicting or unowned migration state must be investigated rather than
  deleted.
- Startup performs no schema activation, fixture seed or consent.

## Private credential setup and presence check

1. Run make provider-setup to create the private credential file.
2. Fill the three fields in local-setup/.env.providers using a local editor.
3. Run make provider-check to confirm that every field is present.

```sh
make provider-setup
# Fill the three fields in local-setup/.env.providers using a local editor.
make provider-check
```

The equivalent stack actions are init-providers and check-providers.

### Credential file rules

| Rule area | Rule |
| --- | --- |
| Creation | Setup creates an ignored, owner-only mode 0600 file if it is absent and preserves an existing valid file |
| Accepted fields | Exactly `DEEPGRAM_API_KEY`, `OPENAI_API_KEY` and `ELEVEN_API_KEY` |
| Values | Literal data, not shell code |
| Handling | Never source the file, use `cat` or `printenv` to share it, put values in command arguments (argv) or paste them into reports |
| Ownership after editing | Keep the file owned by the local user with mode 0600 |
| Fail-closed cases | Symlinks, hardlinks, duplicate or unknown fields, unsafe permissions and invalid or missing values fail closed |

### What the presence check establishes

- provider-check prints only named presence booleans and performs no provider
  call.
- It exits with code 2 while any field is empty.
- A successful presence check establishes neither account credit nor model or
  voice access.
- Keys stay outside the browser, control API, durable worker, collector, local
  model engines and build layers.

## Interactive start and stop

```sh
make provider-start
.venv/bin/python local-setup/stack.py status
.venv/bin/python local-setup/stack.py worker-status
make provider-stop
```

The stack action names are start-provider and stop-provider.

### What start-provider does

1. Requires all three keys.
2. Builds the shared runtime.
3. Runs the read-only preflight of the ACTIVE v4 (or v5) schema and the
   same-scope fixtures.
4. Enables the native agent, API, durable worker and local Jaeger with trusted
   provider_real mode.

- Only the native service receives the three provider credentials.
- Start runs no local model engines and downloads no weights.
- Dependency and image preparation may use the network separately from
  inference.
- The retained v2 gate qualified the declared account, model and speech
  scenario. Future access and operation failures still require fresh setup and
  actual progress.

### If start-provider fails

If start-provider fails after the serving step has begun, the stack manager runs
the stop-provider cleanup and reports
`{"status":"failed","code":"provider_start_failed","stage":"serving","cleanup_incomplete":<true|false>}`.
cleanup_incomplete is true when that cleanup did not complete.

### Use the console

1. Open the loopback console and enter the separate local operator token, as
   documented in the [setup guide](../local-setup/README.md). The model API keys
   never enter the console.
2. Resume a case.
3. Choose the labelled prerecorded input or the explicitly permission-controlled
   microphone.
4. Join.

- The badge distinguishes configured from native-profile-matched readiness. It
  does not certify recognition or playback.
- Interrupt and End release media resources without business cancellation.
- Exact quote and revision approval remains a separate authenticated workflow
  action.

### Stop the provider profile

Use provider-stop when leaving the provider profile. It:

1. requests the existing 35-second native and worker drain;
2. restores ordinary API and scripted mode;
3. removes the credential-bearing native container.

It attempts the credential-container removal even if another shutdown step
fails. Incomplete cleanup remains a failure. Named volumes, accepted work and the
private credential file remain. Stop does not need to read provider keys.

stop-business also removes the native conversation-agent container after
draining, and start-business recreates it. Provider keys therefore do not remain
in a stopped container's configuration.

A destructive reset is not a normal stop or recovery step.

## Joined three-project showcase

The joined P1/P2/P3 showcase has its own explicit provider mode on the host:

```sh
make channel-policy-demo-start-provider CHANNEL_POLICY_PROFILE=$PWD/.local/showcase-2
```

| Aspect | Joined showcase provider behavior |
| --- | --- |
| Credentials | Reads the same private credential file with the strict loader and passes the three keys only to each room's native worker process |
| Models | The worker reuses the fixed Deepgram nova-3, OpenAI gpt-5.4-mini and ElevenLabs eleven_v4_turbo adapters described above |
| Tools | A toolless OpenAI plugin, because that runtime offers the model no tools |
| Reply timing | The P2 runtime's scheduled-reply timing, so durable dispatch never waits for speech playout |
| Dispatch decision | The persisted dispatch decision stays the deterministic investigation rule; models produce transcripts and replies only |
| Browser header | Shows `LOCAL / REAL PROVIDERS` once the native agent reports the matching mode |

The [0046 work item](work-items/0046-joined-showcase-providers-and-demo.md)
records the selected actual journeys. They are separate from the P1-20 gate.

## Explicit local certificate trust

The default runtime uses the pinned image's operating system (OS) trust store. A
local network may require an additional approved certificate authority (CA)
chain that the host already trusts.

### Bundle requirements

| Requirement | Rule |
| --- | --- |
| Selection | Select a public certificate-only bundle in PEM (Privacy-Enhanced Mail) format explicitly |
| Automatic changes | No certificates are downloaded or added automatically |
| Repository | Keep private keys and issuer details out of the repository |
| Accepted file | The strict reader accepts an absolute regular single-link file owned by the operator or root, without group or world write access |
| Size | At most 512 KiB |
| Rejected content | Symlinks, private keys, comments, malformed data and non-CA certificates |

### Interactive profile

```sh
.venv/bin/python local-setup/stack.py start-provider --provider-ca-bundle /absolute/path/approved-ca-bundle.pem
```

- The manager atomically retains one public snapshot in ignored generated setup
  state and recreates the owned business containers to activate it.
- Only the native container mounts that snapshot, read-only at its verified OS
  CA-file location.
- The API and durable worker receive neither a CA mount nor a trust environment
  setting.
- Provider keys remain the same three private fields.
- Normal startup does not read ambient CA or proxy settings or activate this
  option.
- Stop retains the public configuration snapshot alongside other generated setup
  state.

### Registered isolated gate

For the registered isolated gate, select the same public trust source
explicitly:

```sh
P1_PROVIDER_CA_BUNDLE=/absolute/path/approved-ca-bundle.pem P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

- The wrapper binds the selected certificate digest and byte count to fresh
  runtime evidence.
- The helper verifies native readability, actual mounted bytes, the pinned
  client's default trust path, hostname checking and CERT_REQUIRED. It also
  verifies that the API and worker lack this mount.
- Only safe numeric and hash metadata is retained.
- The run owns a separate snapshot until native container removal is verified.
  Incomplete cleanup retains it and fails visibly.
- The recorded input hash is checked again after media work.
- Certificate and hostname verification, fixed provider routes, output caps and
  deadlines stay enabled.

## Fresh provider acceptance gate

The isolated gate uses its own API, worker, native agent, UI, schema, volumes and
synthetic fixtures, each labelled with a universally unique identifier (UUID). It
reuses the owned foundation PostgreSQL and LiveKit network and an owned
collector. It does not reset the persistent workspace.

### Prerequisites

1. Prepare the current installed application and console images and the host
   console build.
2. Prepare the explicit three-key file, the restricted PostgreSQL roles and the
   managed Playwright browser.
3. Stop the ordinary conversation worker. Use provider-stop if the interactive
   provider profile was started.

- The isolated helper prepares only its owned authority and fixtures. Normal
  persistent activation is separate.
- No local cache, inference network or Whisper/Qwen/Piper container is required
  for this provider gate.

### Run the gate

```sh
make provider-stop
P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

- The wrapper defaults to local_real unless the trusted environment explicitly
  selects provider_real.
- P1-20 remains harness mode live in either real profile. Live means actual
  inference and does not mean hosted deployment.

The direct source-bound helper is also available:

```sh
.venv/bin/python local-setup/scripts/phase_g_demo.py --mode provider_real --work-seconds 600
```

- Optional --browser-executable selects an existing absolute executable.
- Optional --artifact-root must be an absent absolute child of the repository's
  .local/validation directory.

### Cases and budgets

Two actual browser cases retain the same eight-pending-inquiry cohort, End and
fresh consumer, held PostgreSQL and supplier control, and exact
human-confirmation assertions.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Work deadline | 600 seconds | Isolated gate helper | With 180 seconds reserved for owned cleanup |
| Wrapper total deadline | Original 840 seconds | Registered P1-20 wrapper | Under the 900-second catalog supervisor |
| Browser interruption | At most 1.5 seconds | Browser cases | None |
| Real commit | 12 seconds | Browser commit control | None |
| Other remote procedure calls (RPCs) | 8 seconds | Other browser controls | None |
| Browser cleanup | 5 seconds | Browser cases | None |
| Native ASR and TTS | 10 seconds each | Native agent | None |
| LLM | 30 seconds | Native agent | None |

These caps remain finite. No nested automatic retries extend them.

### Credentials and evidence

- The helper privately validates keys at explicit runtime. It writes a temporary
  mode 0600 Docker env file only for the UUID-owned native process.
- It does not copy key values into command arguments or evidence.
- Fresh evidence must prove nonzero ASR input and final recognition, LLM input and
  output usage, generated speech and advancing browser playback.
- The wrapper independently revalidates the numeric SDK records, run-bound
  browser statistics and sanitized raw OpenTelemetry Protocol (OTLP) data with
  all three exact model/provider pairs.
- Missing setup, 401/429 responses, timeout, missing progress, skips, stale
  artifacts or incomplete owned cleanup cannot pass.

### Owned durable-worker checkpoint

The real-media helper pauses and later resumes its own durable worker. These
setup observations remain distinct from business results and media
qualification.

To reach the pause:

1. After installed-source validation, the helper sends SIGUSR1 only to its exact
   UUID-owned running worker. A request flag is not an acknowledgement.
2. WorkerRuntime reaches its quiescent outer-loop checkpoint only after the child
   is reaped, its lease is released and post-step queue SQL has finished.
3. The helper uses installed WorkerHealth.is_quiescent(maximum_age_seconds=10)
   and requires a separate active=0 durable snapshot.
4. The helper applies the existing OS pause.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Setup deadline | Original 100 seconds | Arming, signalling, health acknowledgement, idle observation and pause | One deadline shared by all five |
| Recovery clock | Original 45 seconds | Unpause, SIGUSR2 and fresh WorkerHealth.ready acknowledgement | Includes resume overhead |
| Resume and close | Existing 12-second ceiling | Resume and close together | A failed attempt's deadline is not reset |

An active=0 sample alone cannot prove that the parent is out of SQL.

Recovery and resume rules:

- Recovery begins its original 45-second clock before unpause, SIGUSR2 and fresh
  WorkerHealth.ready acknowledgement. The window includes resume overhead rather
  than starting a new window after the reply.
- Ready may already report one active child.
- The helper owns possibly lost signal and pause acknowledgements before issuing
  them. Unresolved resume or cleanup remains non-passing.
- Resume and close share the existing 12-second ceiling, without resetting a
  failed attempt's deadline.
- SIGTERM and SIGINT remain sticky shutdown requests. SIGUSR2 cannot reverse
  shutdown.
- No model, provider or browser control gains maintenance or mutation authority.

The retained proof has an exact nine-field worker_quiescence record: schema,
resumed phase, observed and resolved flags, one quiesce and one resume signal,
and positive health and idle observation counts bounded at 2,001. The independent
real acceptance consumer rejects absent, unknown, coerced, partial or
repeated-signal proof.

## Observability, resources and retention

### Local observations

- Local evidence observes native, API and worker control group (cgroup) CPU and
  memory windows.
- External provider CPU, memory and internal capacity are unobserved.
  Downloaded-model or engine counters cannot substitute for remote usage.
- Numeric usage, control timings, current-task trace correlation and independent
  supplier and receiver receipts are separate facts.
- A response, hint, transcript or playback event is never business authority or
  human acknowledgement.

### Diagnostics

- Native logs keep the established five-field finite schema.
- Prompts, transcripts, audio bodies, headers, key values, raw provider errors and
  exception chains are excluded from retained diagnostics.
- Trace copies admit fixed model and provider labels. Known upstream display
  aliases are normalized without changing SDK observations.
- Browser trace, video and HTTP Archive (HAR) recording remain disabled, and
  screenshots require empty passwords.

### Provider data retention

Content-free local evidence does not establish provider zero data retention.

| Provider | Retention behavior | Notes |
| --- | --- | --- |
| Deepgram | Requests opt out of model improvement | None |
| OpenAI | store=false | Not a blanket retention promise |
| ElevenLabs | Logging remains the pinned default true | Its [text-to-dialogue zero-retention option](https://elevenlabs.io/docs/changelog/2026/6/8) requires enterprise entitlement and is not silently enabled or substituted here |

Use synthetic demonstration data. Do not infer production capacity, model quality
or a cost guarantee from one passing local scenario.

## Nova 2.5 Sonic alternative

Nova 2.5 Sonic is a verified SDK alternative, not this implemented three-stage
profile.

- Amazon Web Services (AWS) documents model ID amazon.nova-2-5-sonic and four
  supported in-region locations.
  [The model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-5-sonic.html)
  and [LiveKit integration](https://docs.livekit.io/agents/models/realtime/nova-sonic/)
  describe its bidirectional speech-to-speech pipeline.
- The pinned AWS plugin exposes with_nova_sonic_2_5 through its realtime extra.
- That transport requires standard AWS credentials, including temporary-session
  credentials when applicable, according to
  [AWS API compatibility](https://docs.aws.amazon.com/bedrock/latest/userguide/models-api-compatibility.html).
  It is not an interchangeable Bedrock API-key field.
- Adopting it requires a separate reviewed runtime, dependency and real-media
  qualification. The existing strict three-key provider file does not accept AWS
  fields.
