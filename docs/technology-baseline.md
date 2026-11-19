# Technology baseline and version policy

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the selected versions, their upstream constraints, and how candidates are promoted and pins updated |
| Audience | Engineers and coding agents who add, upgrade or review dependencies |
| Scope | Runtime, SDK, application, tool, image and inference selections; excludes setup commands and evidence rules |
| Owns | Candidate versions, compatibility, promotion and updates |
| Related | [Machine-readable baseline](../harness/stack-baseline.json) · [Local setup guide](../local-setup/README.md) · [Validation plan](validation-plan.md) · [Local real inference](local-real-inference.md) · [Provider demo](provider-demo.md) |

## Overview

This document records the selected runtime, SDK, application, tool and image
versions, their upstream compatibility constraints, how candidates are promoted
and how pins are updated.

| Section | What it covers |
| --- | --- |
| [Installed foundation versions](#installed-foundation-versions) and [installed application and development tooling](#installed-application-and-development-tooling) | The exact current selections |
| [Inference profile selections](#inference-profile-selections) | The explicit local_real and provider_real profiles |
| [Future dependency candidates](#future-dependency-candidates) and [preserve upstream compatibility](#preserve-upstream-compatibility) | The optional Node Agents SDK and the upstream constraints to keep |
| [Reproducible pins and upgrades](#reproducible-pins-and-upgrades) | Pinning rules and the upgrade procedure |
| [Dependency inventory tool qualification](#dependency-inventory-tool-qualification) | Requirements for a future scanner |
| [Promotion gates and current evidence](#promotion-gates-and-current-evidence) | The STACK-01 to STACK-07 gates |
| [Dependency checkpoints](#dependency-checkpoints) | Dependency changes recorded by individual phases |

### Version policy

Use the latest stable releases compatible with LiveKit's declared constraints.
Then retain exact locks and image references for reproducibility.

### Current status

The current local foundation and the opt-in P1 business profile are installed,
with selected local host, container and browser evidence.

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 for the local proof of concept (POC) | Qualified using provider_real v2 | [Phase H release qualification](work-items/0019-p1-phase-h-release-qualification.md) |
| local_real profile | Not qualified | [Local real-inference guide](local-real-inference.md) |
| P2/P3 contract and intake slices | Partial: complete product acceptance remains pending | [Promotion gates](#promotion-gates-and-current-evidence) |
| Complete integration and platform promotion | Planned | [Promotion gates](#promotion-gates-and-current-evidence) |

The P1 provider result is retained checkpoint evidence. Its fresh P1-20 rerun
after the v5 upgrade remains open in the
[qualification guide](qualification-gates.md). Workload versions such as
`provider_real` v2 are independent of storage schema versions.

### Authoritative records

| Record | Owns |
| --- | --- |
| [stack-baseline.json](../harness/stack-baseline.json) | The machine-readable version record |
| [uv.lock](../uv.lock), [pnpm-lock.yaml](../pnpm-lock.yaml) and [images.env](../local-setup/images.env) | The actual resolved environment |
| [Local setup guide](../local-setup/README.md) | Setup commands |
| [Portfolio scope](portfolio-scope.md) and [validation plan](validation-plan.md) | Requirements and sufficient evidence |

## Installed foundation versions

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| Python | 3.14.10 | Runtime for the host and the Python container target | [Release](https://www.python.org/downloads/release/python-31410/) |
| livekit-agents | 1.8.11 | Python Agents SDK for the diagnostic agent and the separate native scripted AgentSession | [Release](https://github.com/livekit/agents/releases/tag/livekit-agents%401.8.11) |
| livekit | 1.2.0 | Python RTC SDK | Installed within the selected Agents dependency constraints |
| livekit-api | 1.2.2 | Python server API | Installed within the selected Agents dependency constraints |
| Node | 26.13.0 pinned container target; 24.22.2 validated host | Node runtime | [Node releases](https://nodejs.org/en/download) |
| livekit-client | 2.23.0 | Browser SDK for M1 diagnostics and the business workspace | [Release](https://github.com/livekit/client-sdk-js/releases/tag/v2.23.0) |
| LiveKit server | 1.13.11 | Self-hosted media server | Pulled and pinned by digest; [release](https://github.com/livekit/livekit/releases/tag/v1.13.11) |
| PostgreSQL | 18.6 | Pinned local authority through explicit booking schema v5 | Default M1 stays on SQLite; serving supports ACTIVE v4/v5 and owner preparation upgrades through v5 |
| nginx-unprivileged | stable-alpine3.24 | Static console runtime that serves the production-built console and proxies the local API | Immutable content selected through the digest in `images.env` |
| Jaeger | 2.23.0 | Optional pinned local trace viewer | Viewer availability alone remains insufficient |

Here, RTC means real-time communication, OTLP means OpenTelemetry Protocol and M1
is the original SQLite confirmed-investigation intake.

Evidence boundaries for these selections:

- **Python:** current Python foundation checks and SDK imports were exercised.
- **livekit-agents:** real SDK speech, tool and media paths use local
  deterministic fixtures; no real-inference quality is implied.
- **livekit and livekit-api:** the room-scoped token/API and SDK transport
  foundation was exercised.
- **Node:** the host .node-version and selected source/installed SDK gates use
  Node 24. The pinned build image uses Node 26; its accepted engine range is
  separate from complete host qualification.
- **livekit-client:** the Phase G lane qualifies local scripted WebAudio/WebRTC
  input, actual returned audio, active interruption and fresh-room same-task
  continuation. Physical microphone capture is not qualified.
- **LiveKit server:** local native-SDK host/container text and audio checks passed
  against the self-hosted server.
- **PostgreSQL:** cutover, case/effect/completion and DB-time worker leases have
  separate real-store/process gates.
- **Jaeger:** the Phase G lane inspects filtered native/application OTLP export.
  In-memory local traces do not establish production retention.

### Container references and media evidence

- Exact container references are maintained only in images.env.
- The [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
  records combined local browser and native evidence and the actual runtime and
  browser versions.
- The positive test source publishes bundled pulse-code modulation (PCM) audio
  using WebAudio and real WebRTC, without overriding getUserMedia. Microphone
  permission denial is a separate actual-browser negative check.
- The local scripted path does not establish physical capture, human hearing or
  real-provider quality.

### Platforms

Docker Desktop on macOS arm64 is the tested local platform. The local POC
qualifies the selected macOS host and Linux containers with actual runs. Remote
continuous integration (CI) and publication are outside scope. Existing workflow
definitions are optional automation references.

## Installed application and development tooling

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| uv | 0.13.7 | Python environment: resolve and reproduce it with `uv.lock` | None |
| FastAPI | 0.162.2 | Control API: default M1 plus opt-in scoped business/session HTTP adapters | None |
| Uvicorn | 0.54.0 | Control API: default M1 plus opt-in scoped business/session HTTP adapters | None |
| Pydantic | 2.14.3 | Runtime validation for typed HTTP contracts | None |
| psycopg | 3.3.8 | Database client for the restricted PostgreSQL authority, controlled migrations and bounded adapters | Installed with its binary extra |
| HTTPX | 0.28.1 | HTTP client for local HTTP integration and API test support | None |
| prometheus-client | 0.26.0 | API metrics with an isolated registry and protected bounded-label metrics | Direct pinned local dependency |
| pytest | 9.2.0 | Installed Python test tool | Reports must identify which checks actually ran |
| Ruff | 0.17.4 | Installed Python lint tool | Reports must identify which checks actually ran |
| mypy | 2.4.1 | Installed Python type tool | Reports must identify which checks actually ran |
| pnpm | 12.18.0 | JavaScript package manager for the root workspace and frozen dependency resolution | None |
| TypeScript | 7.0.2 | Strict console compilation | None |
| @types/node | 26.6.6 | Node types for strict console compilation | None |
| Vite | 8.3.6 | Browser production asset build | None |
| Vitest | 5.1.0 | Strict controller/adapter tests | Exact executed totals belong in phase evidence |
| setuptools | 84.2.1 | Python build backend | Exact build-system pin in `pyproject.toml` |

The current packages are declared in [pyproject.toml](../pyproject.toml) and the
[console package](../apps/local-console/package.json). Installed tooling is not an
assertion that every possible lint or type check passed. Retain the executed
commands and results in local evidence.

### Frozen installed bytecode

The shared Python image runs a frozen, non-editable production installation with
uv --compile-bytecode during the build. Installed child processes can reuse the
image caches, while the runtime setting PYTHONDONTWRITEBYTECODE=1 prevents cache
writes.

- This is build and runtime preparation under the same pinned Python,
  dependencies and source contracts. Source and image verification and the actual
  gates remain required.
- No stable speedup, throughput or binary-reproducible archive claim follows from
  it.

## Inference profile selections

The trusted inference mode enum is scripted (the default), local_real or
provider_real.

### Local real-inference profile (local_real)

The explicit local_real checkpoint adds livekit-plugins-openai 1.8.11, using the
existing compatible OpenAI 3.46.0 and httpx2 2.16.0 resolution.

- The runtime uses only fixed private local endpoints. Ambient authorization and
  proxy configuration are excluded.
- Actual local engine, model and media qualification remains pending. The default
  scripted and offline lanes do not call those engines.
- Retain the actual browser executable and version in local evidence.

#### Explicit local real-inference selections

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| livekit-plugins-openai | 1.8.11 | Native LLM plugin | Uses the selected Agents 1.8.11; no remote provider fallback |
| OpenAI | 3.46.0 | Existing compatible resolution used by the plugin | None |
| httpx2 | 2.16.0 | Existing compatible resolution used by the plugin | None |
| Ollama | 0.40.15 | Local LLM with qwen3:4b-instruct Q4_K_M | Immutable engine/model declaration; actual model/tool outcomes pending |
| whisper.cpp | 1.9.5 | Local ASR with base.en | Built from selected release; actual recognition quality pending |
| piper-tts | 1.8.0 | Local TTS with en_US-ljspeech-medium | Separate engine process; generated-speech/media qualification pending |
| onnxruntime | 1.31.1 | Local TTS runtime alongside piper-tts | Separate engine process; generated-speech/media qualification pending |

In the table, LLM means large language model, ASR means automatic speech
recognition and TTS means text-to-speech.

The model cache holds ten exact files, 2,708,795,741 bytes including the 859-byte
Ollama manifest. Fetch and checksum verification are explicit; weights being
present does not establish inference.

- [Model declarations](../local-setup/models/local-model-manifest.json) own the
  exact byte sizes and digests and the public release and license sources.
- The [operations guide](local-real-inference.md) owns preparation, runtime
  isolation, resource ceilings and pending gates.
- The frozen declaration is an input snapshot. Its original status label is not
  rewritten when a cache or runtime check passes.

### Explicit provider-real profile

provider_real uses three provider plugins, all pinned to 1.8.11 with Agents
1.8.11. It is a separately selected profile, never an automatic fallback from a
failed local engine.

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| livekit-plugins-deepgram | 1.8.11 | Speech recognition | Fixed selection: Deepgram nova-3 batch recognition on manual flush |
| livekit-plugins-openai | 1.8.11 | Language model | Fixed selection: OpenAI gpt-5.4-mini streaming Chat Completions with none reasoning and at most 128 output tokens |
| livekit-plugins-elevenlabs | 1.8.11 | Speech synthesis | Fixed selection: ElevenLabs eleven_v4_turbo chunked HTTP PCM speech |

- The [provider operations guide](provider-demo.md) owns explicit setup, check,
  start and stop, and the trusted provider P1-20 selector.
- Three private keys reach only the native process. Local model caches and
  engines are unnecessary.
- The selected provider_real v2 gate passed both actual browser cases with
  cleanup. P1 V1 is qualified for the local POC using provider_real v2.
- External provider CPU and memory are unobserved. No zero-retention or
  model-quality guarantee follows from local content-free telemetry.
- Default offline and scripted checks make no provider calls.

## Future dependency candidates

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| @livekit/agents | 1.9.5 | TypeScript Agents SDK candidate | Not installed in the current console and control-API foundation; [release](https://github.com/livekit/agents-js/releases/tag/%40livekit/agents%401.9.5) · [release package metadata](https://api.github.com/repos/livekit/agents-js/contents/agents/package.json?ref=%40livekit%2Fagents%401.9.5) |

- Introduce it only if a selected component hosts a Node realtime agent. Then
  resolve and exercise its RTC and native peers before promotion.
- Ordinary TypeScript HTTP specialists need typed handlers, runtime schemas and
  capability and provider clients, not an additional media runtime.

## Preserve upstream compatibility

### Python constraints

Python Agents 1.8.11 declares these upstream requirements
([release metadata](https://github.com/livekit/agents/blob/livekit-agents%401.8.11/livekit-agents/pyproject.toml)),
and the repository applies a narrower local support policy:

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python for Agents 1.8.11 | `>=3.10,<3.15` | Upstream requirement |
| livekit for Agents 1.8.11 | `==1.2.0` | Upstream requirement |
| livekit-api for Agents 1.8.11 | `>=1.2.2,<2` | Upstream requirement |
| Python for the root and all three project Python distributions | `>=3.14,<3.15`; selects 3.14.10 | Local support policy |

- This narrower local support policy does not advertise every version allowed by
  the upstream SDK.
- Python 3.15 is outside the SDK range.
- Preserve the upstream constraints rather than independently forcing
  incompatible transitive upgrades.

### Future Node constraints

For the future Node Agents integration, the selected release declares these
ranges:

| Requirement | Version or value | Notes |
| --- | --- | --- |
| @livekit/rtc-node range in the selected release workspace | `^1.1.0` | [Workspace metadata](https://api.github.com/repos/livekit/agents-js/contents/pnpm-workspace.yaml?ref=%40livekit%2Fagents%401.9.5) |
| Zod declared by the Agents package | `^3.25.76 \|\| ^4.1.8` | [Release metadata](https://api.github.com/repos/livekit/agents-js/contents/agents/package.json?ref=%40livekit%2Fagents%401.9.5) |

- These are compatibility constraints, not claims of an installed Node agent.
- If that optional runtime is selected, native imports and actual Node-agent tests
  must validate the resolved selection.
- HTTP specialist contract tests remain required regardless of that dependency
  choice.

## Reproducible pins and upgrades

### Pin artifacts

Use exact direct pins, uv.lock, pnpm-lock.yaml, runtime version files and
versioned image references with recorded digests.

- A readable mutable tag is acceptable only when the accompanying digest fixes the
  actual image content.
- Keep secrets outside tracked configuration and diagnostics.

### When to refresh versions

Hold the validated frozen baseline within each feature slice. Recheck upstream
stable direct versions at a new SDK or provider integration, an intentional
upgrade and a portfolio release. A version refresh is not an automatic
prerequisite for unrelated feature edits.

### Upgrade procedure

1. Change pins and locks together.
2. Rerun the affected native, contract, correctness, local-media and benchmark
   checks.
3. Preserve the preceding working environment until its replacement passes.

Never relabel older evidence as if it used a newer runtime or provider.

### Stable selections and required beta transitives

Select stable direct dependencies and exclude unsupported overrides. The SDK
currently requires beta OpenTelemetry transitive dependencies, including the
0.66b2 instrumentation packages, and uv.lock preserves those upstream
constraints. These required transitives are not a reason to override SDK
compatibility or to describe every resolved package as a stable release.

## Dependency inventory tool qualification

No repository software bill of materials (SBOM) or vulnerability scanner is
currently qualified. Before adding one, freeze the local tool, version and
configuration and the exact lockfiles as a bounded tooling slice.

### Inventory coverage

- The current pnpm lockfile contains two YAML documents. The selected tool must
  process the application importer and the resolved transitive graph, not stop
  after the package-manager configuration.
- Verify known direct production and development entries, including
  livekit-client and browser and build tooling, plus known resolved transitives,
  against the frozen lock.
- Cover every implemented workspace package, including the existing P2/P3
  importers, and the Python lock graph.

### Inventory gate evidence

- Retain positive inventory output, and a negative first-document-only fixture or
  intentionally incomplete inventory that the gate rejects.
- A zero-entry result, a missing application importer or an omitted package fails
  inventory completeness.
- Record scan freshness, advisory-database availability, exclusions and
  unresolved results separately from graph coverage.
- Do not claim vulnerability or supply-chain qualification from a lockfile parser
  alone.

Dependency pins remain unchanged in this review. Upgrades require the existing
intentional compatibility checkpoint.

## Promotion gates and current evidence

Each STACK gate records the observed foundation evidence and the work that remains
before promotion.

| Gate | Observed foundation evidence | Remaining promotion work |
| --- | --- | --- |
| STACK-01 Versions and compatibility | Exact runtime, SDK, application, tool and image selections recorded | Refresh public metadata at each integration or upgrade |
| STACK-02 Clean resolution | uv.lock, pnpm-lock.yaml and image digests exist and support the current foundation | Add and reproduce future provider/specialist dependencies with frozen resolution |
| STACK-03 Native imports | Python SDK imports, host/container transport and selected provider_real v2 native integration exercised | Qualify additional provider/native integrations as introduced; Node Agents peers only for an actual Node realtime component |
| STACK-04 Language checks | Root/P1/P2/P3 Python correctness/typing, console app/E2E checks, P2/P3 TypeScript contract, standalone/HTTP checks and selected dispatch/coordinator PostgreSQL/process gates | Complete joined integration and charter release; repeat affected lifecycle and media gates after changes |
| STACK-05 Local room | Diagnostic/M1, Phase G scripted media and selected provider_real v2 P1 browser inference/playback qualified in their declared scopes | Physical capture, local_real and P2/P3 integration/charter qualification |
| STACK-06 Local runtime parity | Selected P1 host/Linux and P2/P3 isolated installed consumers passed in their recorded scopes; Python 3.14-only metadata | Complete joined installed/container qualification and any newly advertised platform; no remote CI prerequisite |
| STACK-07 Retained evidence | Local smoke/build, historical H1, current full H2, selected provider media, installed packages and reviewed P1 release index retained | P2/P3 workload/media/platform evidence and optional local_real qualification for their respective claims |

The overall stack remains partially validated.

- P1-01 through P1-05 have executable SQLite acceptance and recovery evidence.
- P1 local V1 coverage passed.
- Complete P2/P3 product acceptance remains pending.
- Use the harness catalog for current complete runner registrations.

Later P1 phase contributions retain separate database and process, browser and
native, and trace evidence. They do not establish P2/P3 behavior, real-model
quality, production capacity or a completed portfolio release.

## Dependency checkpoints

These checkpoints record the dependency changes introduced by individual phases,
in delivery order.

### Phase G dependency checkpoint

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| OpenTelemetry API, SDK and HTTP exporter | 1.45.2 | Explicit local direct dependencies for the new tracing consumer | Already present in the SDK-compatible lock; not a provider or SDK upgrade |
| Playwright | 1.65.0 | Isolated actual browser media verification | Exact development-only dependency |
| pnpm | 12.18.0 | Validates the frozen workspace lock | None |

- The native consumer uses the frozen Agents 1.8.11 and browser SDK 2.23.0 pins.
- Required SDK beta transitives remain as resolved.
- Local browser runs record the installed browser version. The browser is not
  distributed in the application image.
- That historical Phase G checkpoint introduces no inference-provider package or
  implicit model download.
- New speech assets include their local fixture provenance manifest.
- Native input and status controls require actual RoomIO readiness and active SDK
  state.

### Phase H workload checkpoint

The [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md)
records the locally measured seeded inquiry baseline for S-I06 and the first
P1-I27 slice. Its declarations were frozen before measurement against the existing
installed baseline. No SDK, provider or production dependency change was needed
for H1.

H2 reliability and the P1-I26 host/Linux artifact, API and genuine-consumer gates
passed separately. P1 V1 is qualified for the local POC using provider_real v2.
local_real remains unqualified, P2/P3 slices are partial, and complete product
release remains pending. No local fault window or configured container ceiling is
a production capacity result.

### P2/P3 contract and storage checkpoint

This checkpoint adds these packages:

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| pg | 8.23.1 | PostgreSQL client added by the P2 server subpath | Pure JavaScript |
| @types/pg | 8.23.1 | Types for pg, added by the P2 server subpath | None |
| Prettier | 3.9.10 | Root format gate for P2/P3 TypeScript source, tests and public examples | Pinned root development tool; preserves the existing console source |

No native driver or object-relational mapper (ORM) is introduced. The source
package's browser-safe codec does not import this server path.

Transaction and pool contracts were checked against the maintained
[transaction guide](https://node-postgres.com/features/transactions) and
[pool API](https://node-postgres.com/apis/pool):

- use one checked-out client per transaction;
- bound application admission as well as connections;
- observe idle client errors;
- close owned clients explicitly.

Actual versions are frozen in package manifests and pnpm-lock.yaml. These docs do
not assert later releases.

The P3 TypeScript policy-contract package reuses the existing TypeScript, Vitest
and Node types. Its HTTP handler and client use Node built-ins, with no new
runtime provider or RTC dependency. Neither package changes P1 Python production
dependencies or implicitly starts a service. The HTTP and standalone slice retains
the frozen versions, and no new dependency resolution is introduced. Actual
public-archive and Node host/Linux observations belong to the
[work item](work-items/0027-p2-standalone-and-p3-http.md).

### Read-only submission and dispatch checkpoint

| Package | Version | Used for | Notes |
| --- | --- | --- | --- |
| agent-continuity[postgres] | 0.1.0 | Actual public library dependency declared by P3 | The workspace and lock record that edge |

- The existing pinned SDK, psycopg and other third-party selections are retained
  through offline resolution.
- Its Python HTTP client uses native asyncio streams, with no added HTTP or
  provider runtime dependency.
- P1's read-only work profile is explicitly owner-installed, and P2's dispatch
  schema has an explicit v1-to-v2 upgrade. Neither starts a service or migrates on
  ordinary import.

The [phase work item](work-items/0028-p2-dispatch-and-p3-coordinator.md) owns the
executed compatibility, artifact and resource evidence. Models, media and complete
P2/P3 platform and release qualification remain separate.

### Native adapter dependency edge

The [completed native/deadline handoff](work-items/0036-native-input-and-deadline-cancellation.md)
reconfirmed the selected stable Python
[Agents 1.8.11 release](https://github.com/livekit/agents/releases/tag/livekit-agents%401.8.11)
and browser
[client 2.23.0 release](https://github.com/livekit/client-sdk-js/releases/tag/v2.23.0)
on 11 November 2026.

- The new optional channel-continuity native extra declares the already selected
  Python SDK. It changes workspace dependency metadata, with no resolved-package
  version changes. The browser lock and image selections are unchanged.
- Default Python codec imports remain SDK-independent.
- Installed pinned source and actual SDK regression tests govern compatibility. A
  current web page alone cannot establish it.

The optional native page and host adapter passed its selected actual six-group
native gate and isolated Python and npm package gates. Final selected phase checks
passed.

- The Python artifacts retain six runtime payloads and the optional pinned SDK.
  Fifty-five unadapted local tests passed.
- The npm artifact retains seventy-eight current payloads with exact public v6
  PostgreSQL/HTTP replay.
- Host SDK processes connect to the existing Docker selective forwarding unit
  (SFU). No new default application image, Compose service, paid provider or
  inference fallback is introduced.
- P3's unchanged production package is freshly built and installed for the
  selected deadline gate. Its compatible qualified P1 wheel is reused with current
  source and README parity.
