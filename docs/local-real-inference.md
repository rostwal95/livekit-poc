# Local real-inference operations

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to prepare, run, size and qualify the explicit local_real inference profile |
| Audience | Engineers who run or change the local_real profile on a local machine; coding agents |
| Scope | P1 native conversation with local Whisper, Qwen and Piper engines; excludes provider_real operations, remote CI and publication |
| Owns | Explicit prepared local model/engine operations, isolation, resource headroom and qualification boundaries |
| Related | [Local setup guide](../local-setup/README.md) · [Inference work item](work-items/0017-p1-local-real-inference.md) · [Conversation guide](conversation-and-showcase.md) · [Provider operations](provider-demo.md) · [Observability](observability.md) |

## Scope and current evidence

This guide covers the explicit local_real inference profile for the P1 (agent
continuity) native conversation. It explains how to prepare the pinned model
cache, start and stop the local engines, size resource headroom, respect the
timing limits and run the registered P1-20 acceptance case. It is for engineers
who run or change this profile on a local machine. This guide remains
authoritative only for local_real preparation and limits.

Contents:

| Section | Covers |
| --- | --- |
| [Frozen models, cache and licenses](#frozen-models-cache-and-licenses) | The model manifest, cache size, engine versions and license boundaries |
| [Explicit preparation and lifecycle](#explicit-preparation-and-lifecycle) | Commands to prepare the workspace, fetch and verify models, and start and stop engines and services |
| [Isolation and resource headroom](#isolation-and-resource-headroom) | Private endpoints, configured ceilings, the observed host and the declared experiment |
| [Timing, backpressure and failure ownership](#timing-backpressure-and-failure-ownership) | Finite budgets and what a timeout does not mean |
| [UI and authority evidence](#ui-and-authority-evidence) | Inference mode, readiness, prerecorded input and tool authority |
| [Observability and qualification](#observability-and-qualification) | Engine metrics, retained evidence, the isolated browser gate and P1-20 |
| [Explicit provider-real profile](#explicit-provider-real-profile) | How the separately selected provider profile relates to this one |

### What the profile does

The explicit local_real profile connects the native LiveKit AgentSession to three
local engines:

- Whisper for automatic speech recognition (ASR);
- Qwen as the large language model (LLM) for reasoning and tool selection;
- Piper for generated text-to-speech (TTS) output.

The default scripted profile remains the deterministic regression lane. Both
profiles use the same scoped durable P1 service and the same separate exact human
quote confirmation. Complete P2 and P3 acceptance remains pending.

This local-engine profile needs no paid provider, carrier or Cloud account. The
separately selected provider profile requires provider keys; see
[Explicit provider-real profile](#explicit-provider-real-profile).

### Current evidence

| Capability | Status | Evidence |
| --- | --- | --- |
| local_real implementation | Not qualified | The implementation and the verified model cache are present |
| Actual engine inference and browser playback under the declared workload | Not qualified | Pending in the [inference work item](work-items/0017-p1-local-real-inference.md) |
| Combined P1 release qualification for local_real | Not qualified | Pending in the same work item |
| Observed local LLM and media scenario | Not qualified | The attempt did not qualify under current host resource pressure; the work item holds the inspected failure evidence |

- No pinned model or declared resource limit was changed to claim a pass.
- Provider qualification, if obtained separately, does not change that local
  result.
- A successful download, healthy container, configured mode or matched native
  badge is not evidence that recognition, reasoning or speech generation
  succeeded.
- Remote continuous integration (CI), package publication and production or
  global capacity are outside this local proof of concept (POC).

### Related guides

| Document | Purpose |
| --- | --- |
| [Local setup guide](../local-setup/README.md) | Covers foundation startup, credentials, controlled ACTIVE v4 preparation (with its additive v5 step) and the independent supplier and receiver fixtures |
| [Conversation guide](conversation-and-showcase.md) | Owns consent, replay identities, reconnect and reconciliation |

Preserve existing M1 data (the original SQLite confirmed-investigation intake)
and closed phase artifacts.

## Frozen models, cache and licenses

### Model manifest and cache size

The [model manifest](../local-setup/models/local-model-manifest.json) is the
single authority for engine selections, ten file sizes, SHA-256 digests, model
and card URLs, and licenses.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Verified cache total | 2,708,795,741 bytes, approximately 2.709 GB decimal | Model payload | Includes the 859-byte Ollama manifest |
| Fetch hard byte limit | 4 GiB | Fetch declaration | None |

These figures cover model payload only. Images, source builds, dependency
caches, temporary download files and Docker layers need additional disk.

### Engines and license boundaries

| Component | Version | License | Notes |
| --- | --- | --- | --- |
| LLM engine and model | Ollama 0.40.15; `qwen3:4b-instruct`, Q4_K_M | MIT engine; Apache-2.0 model and pinned license layer | None |
| ASR engine and model | whisper.cpp 1.9.5; `base.en` | MIT engine and declared weight license | Retained release license |
| TTS engine and voice | piper-tts 1.8.0; `en_US-ljspeech-medium`; onnxruntime 1.31.1 | Separate GPL-3.0-or-later engine | Voice repository metadata and dataset card have distinct terms |

- The [engine notices](../local-setup/inference/NOTICES.md) and the retained
  voice card explain those separate facts. Do not infer a model's license from
  its engine.
- This POC does not publish the engine images.
- Release-based links and exact model checksums live in the manifest. Do not
  duplicate mutable download selections here.
- The manifest's original declaration status is an input snapshot. It is not
  edited to claim that later cache, inference or media checks passed.

### Cache location and integrity

- Models live under the ignored local-setup/.local/models directory.
- models-fetch is the only network-fetch action. Verification and runtime never
  fetch weights.
- Preparation owns a file lock, a bounded child process and an 1,800-second
  deadline with terminate, kill and reap.
- Missing, corrupt or unexpected cache content fails. Runtime does not silently
  replace corrupt files.
- Public model files are readable by the unprivileged engine user ID (UID).
  Credentials and private process captures have separate private permissions.

### Ollama manifest root

After every declared file verifies, explicit host preparation also creates an
owned, empty ollama/manifests-v2 directory with mode 0755. Ollama's read-only
lookup checks that root before falling back to the pinned legacy manifest.
Existing v2 contents are rejected because they could shadow the verified model.
No manifest migration, weight change or runtime write is performed. See the
[release lookup implementation](https://github.com/ollama/ollama/blob/v0.40.15/manifest/paths.go).

## Explicit preparation and lifecycle

Run every command from the repository root with Python 3.14 and the frozen local
environment prepared by `make bootstrap` (all declared extras and development
dependencies). Installing the compatible plugin does not download model weights.

| Task | Command | Notes |
| --- | --- | --- |
| Prepare the persistent workspace | `.venv/bin/python local-setup/stack.py init`, then the sequence in [Prepare the persistent workspace](#prepare-the-persistent-workspace) | Ordinary foundation plus explicit owner and fixture operations |
| Fetch the models | `python3.14 local-setup/stack.py models-fetch` | The only network fetch of model weights, approximately 2.709 GB |
| Verify the cache | `python3.14 local-setup/stack.py models-verify` | Local byte check of the cache; never downloads or repairs |
| Start only the engines | `python3.14 local-setup/stack.py start-models` | Verifies the cache, prepares engine images and starts the p1-models profile |
| Stop only the engines | `python3.14 local-setup/stack.py stop-models` | Stops the engines and keeps the cache |
| Start the interactive workspace | `python3.14 local-setup/stack.py start-local-real` | Verifies the cache, then starts the engines and the local_real business services |
| Stop the interactive workspace | `python3.14 local-setup/stack.py stop-local-real` | Drains workers, removes the native container, restores scripted mode and stops the engines |
| Inspect the stack | `python3.14 local-setup/stack.py status` | None |
| Prepare the managed browser | `make browser-setup` | Explicit; never happens during a gate |
| Run the isolated browser gate | `.venv/bin/python local-setup/scripts/phase_g_demo.py --mode local_real --work-seconds 600` | After `stop-business` and `start-models`; see [the gate procedure](#run-the-isolated-local-real-browser-gate) |
| Run the registered P1-20 case | `.venv/bin/python -m harness run P1-20` | After all explicit preparation |

### Prepare the persistent workspace

For a fresh interactive workspace, complete the ordinary foundation and the
explicit owner and fixture operations from the repository root:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
```

The [persistent workspace procedure](../local-setup/README.md#first-persistent-p1-business-workspace)
explains retained source and backups, safe retry, matching scope and
existing-target refusals.

- prepare-business activates an auxiliary empty source and upgrades the selected
  authority through v4 and the additive v5 step. It never uses the serving M1
  database.
- On an existing ACTIVE v4 target, prepare-business runs the owner-only v5
  upgrade instead. The
  [lease and worker guide](leases-and-workers.md#what-prepare-business-does)
  lists the outcomes that its report names.
- migrate-postgres alone leaves a STAGING target.
- Phase demonstrations clean their own schemas and do not prepare this
  persistent workspace.
- None of these operations grants confirmation. Model startup performs no
  activation or fixture initialization.
- Already valid ACTIVE v4 or v5 state and same-scope fixtures are retained across
  normal restart.

### Fetch and verify the models

Fetch the declared public models once, then independently verify their bytes:

```sh
python3.14 local-setup/stack.py models-fetch
python3.14 local-setup/stack.py models-verify
```

- models-fetch is the explicit network action of approximately 2.709 GB.
- Repeated verification is local. It does not repair a bad cache by downloading
  another model.
- The stack manager checks the helper's closed numeric result rather than
  accepting arbitrary command output as proof.

### Run only the prepared engines

To run just the prepared private engines:

```sh
python3.14 local-setup/stack.py start-models
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py stop-models
```

start-models performs these steps:

1. Verifies the cache.
2. Explicitly pulls the selected LLM image if it is missing, under a separate
   1,800-second preparation budget.
3. Builds the selected ASR and TTS engines under a 1,200-second budget.
4. Starts the p1-models profile. Engine startup and readiness have their own
   120-second supervisor budget.

Image preparation does not extend inference-request deadlines. start-models
starts no schema migration or fixture initialization. stop-models stops those
engines with a 15-second stop request and retains the cache.

The selected Ollama image has four layers totaling 2,866,193,798 compressed bytes
(approximately 2.866 GB), in addition to the 2.709 GB model cache. Image
preparation is an explicit initial network step and does not qualify model
inference. First builds and dependency preparation can also require internet
access. Prepared inference requests run against local engines.

### Start and stop the interactive P1 workspace

Use these commands after ACTIVE v4 (or v5) schema and fixture preparation:

```sh
python3.14 local-setup/stack.py start-local-real
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py stop-local-real
```

start-local-real performs these steps:

1. Verifies the cached models.
2. Builds the shared application.
3. Runs the read-only schema and fixture preflight.
4. Starts the engines.
5. Enables the native agent, durable worker, API and trace viewer with explicit
   local_real configuration.

It performs no weight fetch, schema activation or fixture initialization.

To use the running profile:

1. Open the normal loopback console.
2. Enter the local operator token.
3. Submit or resume an owned case.
4. Explicitly join voice.

Do not put credentials in shell arguments or retained reports.

stop-local-real performs these steps:

1. Drains the native and durable workers with the existing 35-second stop
   request.
2. Removes the native conversation-agent container after draining.
3. Disables API business mode and restores scripted mode.
4. Stops the engines.

Accepted work and named volumes remain. Ordinary start and start-business
preserve the diagnostic, default-scripted behavior. Normal global stop includes
the model services and preserves data. Destructive reset remains a separate
explicit action.

### Lifecycle budgets and sizes

This guide's preparation, stop and disk figures, in one place:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Model preparation deadline | 1,800 seconds | Model preparation | File lock and bounded child process, with terminate, kill and reap |
| LLM image pull | 1,800 seconds | start-models, when the selected LLM image is missing | Separate preparation budget |
| ASR and TTS engine builds | 1,200 seconds | start-models | None |
| Engine startup and readiness | 120 seconds | p1-models profile supervisor | None |
| Engine stop request | 15 seconds | stop-models | The cache is retained |
| Native and durable worker drain | Existing 35-second stop request | stop-local-real | The native container is removed after draining |
| Selected Ollama image | Four layers, 2,866,193,798 compressed bytes (approximately 2.866 GB) | Disk | In addition to the 2.709 GB model cache |

## Isolation and resource headroom

### Network isolation and endpoints

The p1-llm, p1-stt and p1-tts services use an internal inference network and
publish no host ports. Models are mounted read-only at /models. A missing host
cache is not automatically created as an empty substitute.

Only the configured native agent uses these fixed endpoints. In the table, SDK is
the LiveKit Agents software development kit and PID is a process ID.

| Role | Native endpoint | Memory ceiling | CPU ceiling | PID ceiling |
| --- | --- | --- | --- | --- |
| LLM | http://p1-llm:11434/v1 | 4 GiB | 4 | 128 |
| ASR | http://p1-stt:8080/inference | 1 GiB | 4 | 128 |
| TTS | http://p1-tts:5000/synthesize | 512 MiB | 2 | 128 |
| Native agent | Existing private SDK/health boundary | 512 MiB | 1.5 | 256 |

### Configured ceilings

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Engine ceilings | 5.5 GiB memory and 10 CPU | The three engines together | Added to the existing profile |
| Business and core memory ceilings | 2,816 MiB | Existing complete business and core profile | None |
| Combined memory ceilings | 8.25 GiB | Engines plus the business and core profile | Before Docker, browser and build overhead |
| Engine temporary filesystem | 64 MiB | Each engine | Base services, the host browser and builds add overhead |
| Core-only setup estimate | 2 GiB | Core-only setup | Does not apply to this profile |

Ceilings are limits, not reservations, fixed thread counts or observed peaks.

### Observed host and headroom

The observed CPU-only development host has 24 GB RAM and a Docker virtual
machine (VM) limit of 8,317,267,968 bytes (about 7.75 GiB). These are environment
observations, not a successful inference or capacity result.

- An 8 GiB Docker allocation cannot cover every configured ceiling
  simultaneously.
- Inspect actual available headroom. Run heavyweight builds, package and
  reliability gates, and model workloads serially.
- The manager does not automatically measure host capacity or promise resource
  admission.

### The declared continuity experiment

The declared continuity experiment is one foreground native session plus eight
accepted inquiries, with their durable worker deliberately withheld. It does not
mean eight model sessions, a throughput benchmark or production capacity.

Record actual control group (cgroup) accounted memory and CPU deltas with their
windows. Accounted memory is not resident set size (RSS), and a container's
lifetime peak is not an isolated model peak.

## Timing, backpressure and failure ownership

Audio uses 16-bit pulse-code modulation (PCM16). Browser controls use remote
procedure calls (RPCs).

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Audio input | At most 12 seconds per turn | PCM16 mono 16 kHz input | None |
| Generated audio | At most 20 seconds per response | PCM16 mono 22,050 Hz output | None |
| Native ASR/TTS | 10 seconds each | Native speech operations | Around an 8-second engine child |
| LLM | 30 seconds; 128 output tokens; 256 chunks; 4 KiB output; 64 KiB context | Model requests | None |
| Provider pressure | One active and one waiting native operation; one active speech-engine request with bounded backlog | Native operations and speech engines | None |
| Browser commit acknowledgement | 12 seconds | local_real | Scripted remains 8 seconds |
| Other control RPCs | 8 seconds | Both profiles (local_real and scripted) | None |
| Browser capture/mute/disconnect | Existing 5-second acknowledgement budget | Browser controls | Uncertain cleanup retains ownership |
| Incoming native transcription | Two readers, 16 KiB each; whole-stream 40 seconds | local_real and provider_real | Whole-stream 10 seconds for scripted |

### Transcription stream deadline

The SDK opens a delta transcription stream before synchronized speech finishes.
Its reader deadline therefore covers the whole stream, not one chunk. Room
closure aborts it immediately, and completion or failure clears the owned
deadline.

Native manual-flush ASR uses the SDK streaming extension with vad=None. No voice
activity detection (VAD) model or implicit preloading is introduced.

### What a timeout does not mean

- A timeout does not mean that a database write, supplier effect or accepted
  workflow was cancelled.
- Speech interruption and End release conversation resources without sending
  business cancellation.
- Blocking storage retains capacity until its actual operation ends.
- A separate explicit cancellation command preserves uncertainty at the external
  boundary.
- Missing setup, model or provider failure, required skips, zero tests, missing
  progress or incomplete cleanup remain non-passing.

## UI and authority evidence

### Inference mode and readiness

- The API validates P1_CONVERSATION_INFERENCE as exactly scripted, local_real or
  provider_real, defaulting to scripted. A request cannot override it.
- The strict mint response sets the expected profile.
- Before controls become usable, the selected native AGENT must report that same
  continuity.inference_mode, exact continuity.session_ready=true and an active
  SDK state.
- The badge distinguishes unconfigured, configured and native-profile-matched
  states. None of them certifies model quality.

### Prerecorded input and real-model qualification

Default input is an explicitly published prerecorded WAV through WebAudio and
WebRTC. It is independent of inference mode and never establishes physical
microphone capture or human hearing.

A real-model qualification must inspect actual ASR, LLM and tool usage, generated
speech and advancing browser playback. It must then independently reconcile
persisted work, supplier mutation and receiver delivery.

### Tools and confirmation authority

- Only submit_investigation, get_case and cancel_case are bound no-argument model
  tools.
- Scope, actor, request and key, and task come from trusted composition.
- A prompt, model statement, transcription, playback event or refresh hint cannot
  prepare or approve a quote.
- Exact quote and revision confirmation stays in the authenticated business
  panel.
- Fresh-room rehydration and original business identities remain unchanged.

## Observability and qualification

### Engine metrics and application telemetry

ASR and TTS expose private numeric /metrics snapshots: requests,
succeeded/failed, active/max_active, input/output bytes and cumulative duration
seconds. They are engine observations, not durable business truth or
recognition-quality scores.

Existing protected API metrics, finite safe application events, sanitized traces
and numeric SDK usage identify the configured inference mode. Do not add task,
actor, transcript or model-generated strings as metric labels.

### Retained evidence and privacy

- Private request files and raw child or provider capture are removed after
  completion or controlled failure.
- Retained evidence uses fixed codes, booleans, counts, validated model names,
  timing and resource observations, and provenance digests.
- Prompts, transcripts, audio bodies, headers, credentials and exception chains
  do not belong in retained logs or browser recordings.
- Browser trace, video and HTTP Archive (HAR) recording remain disabled.
  Screenshots require empty password inputs.

### Run the isolated local-real browser gate

The local-real browser gate is separate from the six-case scripted regression.
Its declaration is
[local-setup/workloads/p1-local-real-v1.json](../local-setup/workloads/p1-local-real-v1.json).
The helper creates its own API, worker, native consumer, UI and synthetic state,
each owned by a universally unique identifier (UUID), rather than resetting
normal state.

Prepare the gate in this order:

1. Prepare the ordinary foundation with observability, the current installed
   image and the current host console build.
2. Run make browser-setup from the repository root to prepare the
   Playwright-managed browser. Its default is the Chromium build selected by
   pinned Playwright 1.65.0. Browser installation is explicit and never happens
   during a gate. --browser-executable preserves an explicit existing absolute
   executable override, as described in the local setup guide.
3. Run the commands below. They stop the ordinary business conversation worker,
   keep the verified engines running and start the helper, which creates its own
   UUID-owned native workload.

```sh
python3.14 local-setup/stack.py stop-business
python3.14 local-setup/stack.py start-models
.venv/bin/python local-setup/scripts/phase_g_demo.py --mode local_real --work-seconds 600
```

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Gate work | 600 seconds | Isolated local-real gate | None |
| Owned cleanup | 180 seconds | Isolated local-real gate | None |
| Total deadline | Original 840 seconds | Registered product acceptance wrapper | None |
| Supervisor ceiling | At most 900 seconds | Catalog supervisor | None |
| Runner ceiling | Unchanged 300 seconds | Ordinary harness runners | None |

These are gate budgets, not expanded model or RPC deadlines.

Reports:

- Default reports use a fresh run directory under .local/validation/p1-local-real.
- Optional --artifact-root requires an absent absolute child of the repository's
  .local/validation directory. It rejects symlinks, traversal and existing state.

The helper verifies:

- model checksums, without --fetch;
- source and image ownership;
- actual model usage and generated playback;
- held dependency controls;
- the eight-inquiry continuity cohort;
- independent supplier and receiver truth.

Missing models, media, required checks or cleanup cannot be skipped into a pass.
Exact inspected results belong to the
[active work item](work-items/0017-p1-local-real-inference.md).

### Run the registered P1-20 case

The registered P1-20 case reports harness mode live because it invokes actual
local models. This follows the portfolio's existing real-inference taxonomy. Live
does not require a remote provider, paid account or Cloud. P1-14 and P1-18 remain
lab-mode cases.

Execution mode, configured native profile, actual model results and browser
observations remain separate fields and checks. The wrapper requires a fresh run.
Previous Phase G, Phase H or model reports cannot satisfy the case.

After all explicit preparation above, the registered entrypoint is:

```sh
.venv/bin/python -m harness run P1-20
```

### Qualification status

Actual inference and media qualification remains pending until its phase
evidence is inspected. The
[reliability work item](work-items/0015-p1-reliability-workloads.md) owns the
separately executed restart and slow-provider results. They do not qualify real
speech, model or media behavior.

## Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real is a separately selected profile, never an automatic fallback from
a failed local engine.

provider_real uses livekit-plugins-deepgram, livekit-plugins-openai and
livekit-plugins-elevenlabs, all pinned to 1.8.11 with Agents 1.8.11. Its fixed
pipeline is:

| Stage | Fixed pipeline |
| --- | --- |
| Speech recognition | Deepgram nova-3 batch recognition on manual flush |
| Language model | OpenAI gpt-5.4-mini streaming Chat Completions with none reasoning and at most 128 output tokens |
| Speech synthesis | ElevenLabs eleven_v4_turbo chunked HTTP PCM speech |

- The [provider operations guide](provider-demo.md) owns explicit setup, check,
  start and stop, and the trusted provider P1-20 selector.
- Three private keys reach only the native process. Local model caches and
  engines are unnecessary.
- The selected provider_real v2 gate passed both actual browser cases with
  cleanup. P1 V1 (the fixed first-version scope) is qualified for the local POC
  using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping
source plays the unchanged WAV from sample zero. Closed, muted, replaced,
superseded or not-ready input cannot be restarted by a late reply. Physical
microphone capture is independent. Fixture alignment does not force a model tool
or establish ASR quality.

External provider CPU and memory are unobserved. No zero-retention or
model-quality guarantee follows from local content-free telemetry. Default
offline and scripted checks make no provider calls.
