# Local real-inference operations

Status: Active
Last reviewed: 10 November 2026

## Scope and current evidence

The explicit local_real profile connects the native LiveKit AgentSession to local
Whisper recognition, Qwen reasoning/tool selection and generated Piper speech.
The default scripted profile remains the deterministic regression lane. Both use
the same scoped durable P1 service and separate exact human quote confirmation.
P2/P3 are planned. This local-engine profile needs no paid provider, carrier or
Cloud account; the separately selected provider profile requires provider keys.

The implementation and verified model cache are present. Actual engine inference,
browser playback under the declared workload and combined P1 release qualification
remain pending in the [inference work item](work-items/0017-p1-local-real-inference.md).
A successful download, healthy container, configured mode or matched native badge
is not evidence that recognition, reasoning or speech generation succeeded. Remote
CI, package publication and production/global capacity are outside this local POC.

Read the [local setup](../local-setup/README.md) for foundation startup, credentials,
controlled ACTIVE v4 preparation and independent supplier/receiver fixtures. The
[conversation guide](conversation-and-showcase.md) owns consent, replay identities,
reconnect and reconciliation. Preserve existing M1 data and closed phase artifacts.

## Frozen models, cache and licenses

The [model manifest](../local-setup/models/local-model-manifest.json) is the single
authority for engine selections, ten file sizes, SHA-256 digests, model/card URLs
and licenses. The verified cache totals **2,708,795,741 bytes**, approximately
**2.709 GB** decimal, including the 859-byte Ollama manifest. The fetch declaration
has a 4 GiB hard byte limit. This is model payload only; images, source builds,
dependency caches, temporary download files and Docker layers need additional disk.

| Role | Engine and model | License boundary |
| --- | --- | --- |
| LLM | Ollama 0.40.15; qwen3:4b-instruct, Q4_K_M | MIT engine; Apache-2.0 model and pinned license layer |
| ASR | whisper.cpp 1.9.5; base.en | MIT engine and declared weight license; retained release license |
| TTS | piper-tts 1.8.0; en_US-ljspeech-medium; onnxruntime 1.31.1 | Separate GPL-3.0-or-later engine; voice repository metadata and dataset card have distinct terms |

The [engine notices](../local-setup/inference/NOTICES.md) and retained voice card
explain those separate facts. Do not infer a model's license from its engine.
This POC does not publish the engine images. Release-based links and exact model
checksums live in the manifest; do not duplicate mutable download selections here.
Its original declaration status is an input snapshot and is not edited to claim
that later cache, inference or media checks passed.

Models live under ignored local-setup/.local/models. The only network-fetch action
is models-fetch; verification and runtime never fetch weights. Preparation owns a
file lock, bounded child process and 1,800-second deadline with terminate/kill/reap.
Missing, corrupt or unexpected cache content fails. Runtime does not silently
replace corrupt files. Public model files are readable by the unprivileged engine
UID; credentials and private process captures have separate private permissions.
After every declared file verifies, explicit host preparation also creates an
owned empty 0755 ollama/manifests-v2 directory. Ollama's read-only lookup checks
that root before falling back to the pinned legacy manifest. Existing v2 contents
are rejected because they could shadow the verified model; no manifest migration,
weight change or runtime write is performed. See the
[release lookup implementation](https://github.com/ollama/ollama/blob/v0.40.15/manifest/paths.go).

## Explicit preparation and lifecycle

Run from the repository root with Python 3.14 and the frozen local environment
prepared by make bootstrap (all declared extras and development dependencies).
Installing the compatible plugin does not download model weights.
For a fresh interactive workspace, complete the ordinary foundation and the
explicit owner/fixture operations from the repository root:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
```

The [persistent workspace procedure](../local-setup/README.md#first-persistent-p1-business-workspace)
explains retained source/backups, safe retry, matching scope and existing-target
refusals. prepare-business activates an auxiliary empty source and upgrades the
selected authority to v4; it never uses the serving M1 database. migrate-postgres
alone leaves a STAGING target. Phase demos clean their own schemas and do not
prepare this persistent workspace. None of these operations grants confirmation,
and model startup performs no activation or fixture initialization. Already valid
ACTIVE v4 state and same-scope fixtures are retained across normal restart.

Fetch the declared public models once, then independently verify their bytes:

```sh
python3.14 local-setup/stack.py models-fetch
python3.14 local-setup/stack.py models-verify
```

models-fetch is the explicit approximately 2.709 GB network action. Repeated
verification is local and does not repair a bad cache by downloading another model.
The stack manager checks the helper's closed numeric result rather than accepting
arbitrary command output as proof.

To run just the prepared private engines:

```sh
python3.14 local-setup/stack.py start-models
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py stop-models
```

start-models verifies the cache, explicitly pulls the selected LLM image if missing
under a separate 1,800-second preparation budget, builds the selected ASR/TTS engines
under a 1,200-second budget and starts the p1-models profile. Engine up/readiness
has its own 120-second supervisor budget; image preparation does not extend
inference-request deadlines. It starts no schema migration or fixture initialization.
stop-models stops those engines with a 15-second stop request and retains cache.
The selected Ollama image has four layers totaling 2,866,193,798 compressed bytes
(approximately 2.866 GB), in addition to the 2.709 GB model cache. Image preparation
is an explicit initial network step and does not qualify model inference. First
builds and dependency preparation can also require internet; prepared inference
requests run against local engines.

For the interactive P1 workspace after ACTIVE v4 and fixture preparation:

```sh
python3.14 local-setup/stack.py start-local-real
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py stop-local-real
```

start-local-real verifies cached models, builds the shared application, performs
read-only schema/fixture preflight, starts the engines and then enables the native
agent, durable worker, API and trace viewer with explicit local_real configuration.
It performs no weight fetch, schema activation or fixture initialization. Open the
normal loopback console, enter the local operator token, submit/resume an owned
case and explicitly join voice. Do not put credentials in shell arguments or
retained reports.

stop-local-real drains the native/durable workers with the existing 35-second stop
request, disables API business mode and restores scripted mode, then stops engines.
Accepted work and named volumes remain. Ordinary start and start-business preserve
the diagnostic/default-scripted behavior. Normal global stop includes model
services and preserves data; destructive reset remains a separate explicit action.

## Isolation and resource headroom

The p1-llm, p1-stt and p1-tts services use an internal inference network and publish
no host ports. Models are mounted read-only at /models; a missing host cache is not
automatically created as an empty substitute. Only the configured native agent
uses these fixed endpoints:

| Role | Native endpoint | Memory ceiling | CPU ceiling | PID ceiling |
| --- | --- | --- | --- | --- |
| LLM | http://p1-llm:11434/v1 | 4 GiB | 4 | 128 |
| ASR | http://p1-stt:8080/inference | 1 GiB | 4 | 128 |
| TTS | http://p1-tts:5000/synthesize | 512 MiB | 2 | 128 |
| Native agent | Existing private SDK/health boundary | 512 MiB | 1.5 | 256 |

The three engines add **5.5 GiB and 10 CPU ceilings**. The existing complete
business/core profile has 2,816 MiB of configured memory ceilings; together that
is **8.25 GiB before Docker, browser and build overhead**. Ceilings are limits,
not reservations, fixed thread counts or observed peaks. Each engine also has a
64 MiB temporary filesystem; base services, host browser and builds add overhead. The core-only 2 GiB setup estimate does not
apply to this profile. The observed CPU-only development host has 24 GB RAM and a
Docker VM limit of 8,317,267,968 bytes (about 7.75 GiB); these are environment
observations, not a successful inference or capacity result. An 8 GiB Docker allocation cannot cover every configured
ceiling simultaneously. Inspect actual available headroom and run heavyweight
builds, package/reliability gates and model workloads serially. The manager does
not automatically measure host capacity or promise resource admission.

One foreground native session plus eight accepted inquiries with their durable
worker deliberately withheld is the declared continuity experiment. It does not
mean eight model sessions, a throughput benchmark or production capacity. Record
actual cgroup-accounted memory and CPU deltas with their windows; accounted memory
is not RSS and container lifetime peak is not an isolated model peak.

## Timing, backpressure and failure ownership

| Boundary | Configured finite budget |
| --- | --- |
| Audio input | PCM16 mono 16 kHz; at most 12 seconds per turn |
| Generated audio | PCM16 mono 22,050 Hz; at most 20 seconds per response |
| Native ASR/TTS | 10 seconds each around an 8-second engine child |
| LLM | 30 seconds; 128 output tokens; 256 chunks; 4 KiB output; 64 KiB context |
| Provider pressure | One active and one waiting native operation; one active speech-engine request with bounded backlog |
| Browser commit acknowledgement | 12 seconds for local_real; scripted remains 8 seconds |
| Other control RPCs | 8 seconds for both profiles |
| Browser capture/mute/disconnect | Existing 5-second acknowledgement budget; uncertain cleanup retains ownership |
| Incoming native transcription | Two readers, 16 KiB each; whole-stream 40 seconds local_real/provider_real or 10 seconds scripted |

The SDK opens a delta transcription stream before synchronized speech finishes.
Its reader deadline therefore covers the whole stream, not one chunk. Room closure
aborts it immediately, and completion/failure clears the owned deadline. Native
manual-flush ASR uses the SDK streaming extension with vad=None; no VAD model or
implicit preloading is introduced.

Timeout does not mean a database write, supplier effect or accepted workflow was
cancelled. Speech interruption and End release conversation resources without
sending business cancellation. Blocking storage retains capacity until its actual
operation ends. A separate explicit cancellation command preserves uncertainty
at the external boundary. Missing setup, model/provider failure, required skips,
zero tests, missing progress or incomplete cleanup remain non-passing.

## UI and authority evidence

The API validates P1_CONVERSATION_INFERENCE as exactly scripted, local_real or provider_real,
defaulting to scripted. A request cannot override it. The strict mint response
sets the expected profile; the selected native AGENT must report that same
continuity.inference_mode, exact continuity.session_ready=true and active SDK
state before controls become usable. The badge distinguishes unconfigured,
configured and native-profile-matched states. None certifies model quality.

Default input is an explicitly published prerecorded WAV through WebAudio/WebRTC.
It is independent of inference mode and never establishes physical microphone
capture or human hearing. A real-model qualification must inspect actual ASR,
LLM/tool usage, generated speech and advancing browser playback, then independently
reconcile persisted work, supplier mutation and receiver delivery.

Only submit_investigation, get_case and cancel_case are bound no-argument model
tools. Scope, actor, request/key and task come from trusted composition. A prompt,
model statement, transcription, playback event or refresh hint cannot prepare or
approve a quote. Exact quote/revision confirmation stays in the authenticated
business panel. Fresh-room rehydration and original business identities remain
unchanged.

## Observability and qualification

ASR/TTS expose private numeric /metrics snapshots: requests, succeeded/failed,
active/max_active, input/output bytes and cumulative duration seconds. They are
engine observations, not durable business truth or recognition-quality scores.
Existing protected API metrics, finite safe application events, sanitized traces
and numeric SDK usage identify the configured inference mode. Do not add task,
actor, transcript or model-generated strings as metric labels.

Private request files and raw child/provider capture are removed after completion
or controlled failure. Retained evidence uses fixed codes, booleans, counts,
validated model names, timing/resource observations and provenance digests.
Prompts, transcripts, audio bodies, headers, credentials and exception chains do
not belong in retained logs or browser recordings. Browser trace/video/HAR remain
disabled; screenshots require empty password inputs.

The local-real browser gate is separate from the six-case scripted regression.
It requires prepared running engines, the current installed image and host console
build, the prepared Playwright-managed browser, and the ordinary conversation worker stopped before
creating its own UUID-owned native workload. Its declaration is
[local-setup/workloads/p1-local-real-v1.json](../local-setup/workloads/p1-local-real-v1.json).
After preparing the ordinary foundation with observability and the current host
console build, stop the ordinary business worker before this isolated gate. Keep
the verified engines running; the helper creates its own UUID-owned API, worker,
native consumer, UI and synthetic state rather than resetting normal state:

```sh
python3.14 local-setup/stack.py stop-business
python3.14 local-setup/stack.py start-models
.venv/bin/python local-setup/scripts/phase_g_demo.py --mode local_real --work-seconds 600
```

Run make browser-setup from the repository root before this gate. Its default is
the Chromium build selected by pinned Playwright 1.65.0; browser installation is
explicit and never happens during a gate. --browser-executable preserves an explicit
existing absolute executable override as described in the local setup guide. The work budget is 600 seconds, with 180 seconds for
owned cleanup. The registered product acceptance wrapper has an original
840-second total deadline and its catalog supervisor permits at most 900 seconds.
Ordinary harness runners retain their 300-second ceiling. These are gate budgets,
not expanded model/RPC deadlines. Default reports use a fresh run directory under
.local/validation/p1-local-real; optional --artifact-root requires an absent absolute
child of repository .local/validation and rejects symlinks/traversal/existing state.
The helper verifies model checksums without --fetch, source/image ownership, actual
model usage and generated playback, held dependency controls, the eight-inquiry
continuity cohort and independent supplier/receiver truth. Missing models, media,
required checks or cleanup cannot be skipped into a pass. Exact inspected results
belong to the [active work item](work-items/0017-p1-local-real-inference.md).
The registered P1-20 case reports harness mode live because it invokes actual
local models. This follows the portfolio's existing real-inference taxonomy; live
does not require a remote provider, paid account or Cloud. P1-14/P1-18 remain lab.
Execution mode, configured native profile, actual model results and browser
observations remain separate fields and checks. The wrapper requires a fresh run;
previous G/H/model reports cannot satisfy the case. After all explicit preparation
above, the registered entrypoint is:

```sh
.venv/bin/python -m harness run P1-20
```

Actual inference/media qualification remains pending until its phase evidence is
inspected. The [reliability work item](work-items/0015-p1-reliability-workloads.md)
owns the separately executed restart/slow-provider results; they do not qualify
real speech/model/media behavior.


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
process; local model caches and engines are unnecessary. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping source
plays the unchanged WAV from sample zero. Closed, muted, replaced, superseded or
not-ready input cannot be restarted by a late reply. Physical microphone capture
is independent; fixture alignment does not force a model tool or establish ASR quality. External provider CPU/memory are
unobserved; no zero-retention or model-quality guarantee follows from local
content-free telemetry. Default offline/scripted checks make no provider calls.

This guide remains authoritative only for local_real preparation and limits. The
observed local attempt did not qualify its LLM/media scenario under current host
resource pressure; no pinned model or declared resource limit was changed to
claim a pass. Provider qualification, if obtained separately, does not change that
result. See the inference work item for inspected failure evidence.
