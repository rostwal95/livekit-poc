# Technology baseline and version policy

Status: Active
Last reviewed: 13 November 2026

Use the latest stable releases compatible with LiveKit's declared constraints,
then retain exact locks and image references for reproducibility. The current
local foundation and opt-in P1 business profile are installed with selected local
host/container/browser evidence. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified; P2/P3 contract/intake slices are partial; complete integration/platform promotion remains pending.

The machine-readable record is [stack-baseline.json](../harness/stack-baseline.json).
[uv.lock](../uv.lock), [pnpm-lock.yaml](../pnpm-lock.yaml) and
[images.env](../local-setup/images.env) record the actual resolved environment.
The [local setup guide](../local-setup/README.md) owns setup commands; the
[portfolio scope](portfolio-scope.md) and [validation plan](validation-plan.md)
own requirements and sufficient evidence.

## Installed foundation versions

| Component | Exact selection | Evidence and boundary |
| --- | --- | --- |
| Python runtime | 3.14.10 | Host and Python container target; current Python foundation checks and SDK imports exercised. [Release](https://www.python.org/downloads/release/python-31410/) |
| Python Agents SDK | livekit-agents 1.8.11 | Used by the diagnostic agent and separate native scripted AgentSession. Real SDK speech/tool/media paths use local deterministic fixtures; no real-inference quality is implied. [Release](https://github.com/livekit/agents/releases/tag/livekit-agents%401.8.11) |
| Python RTC and server API | livekit 1.2.0; livekit-api 1.2.2 | Installed within the selected Agents dependency constraints; room-scoped token/API and SDK transport foundation exercised. |
| Node runtime | 26.13.0 pinned container target; 24.22.2 validated host | The host .node-version and selected source/installed SDK gates use Node 24. The pinned build image uses Node 26; its accepted engine range is separate from complete host qualification. [Node releases](https://nodejs.org/en/download) |
| Browser SDK | livekit-client 2.23.0 | Used by M1 diagnostics and the business workspace. Local scripted WebAudio/WebRTC input, actual returned audio, active interruption and fresh-room same-task continuation are qualified by the Phase G lane. Physical microphone capture is not qualified. [Release](https://github.com/livekit/client-sdk-js/releases/tag/v2.23.0) |
| LiveKit server | 1.13.11 | Pulled and pinned by digest; local native-SDK host/container text and audio checks passed against the self-hosted server. [Release](https://github.com/livekit/livekit/releases/tag/v1.13.11) |
| PostgreSQL | 18.6 | Pinned local authority through explicit schema v4: cutover, case/effect/completion and DB-time worker leases have separate real-store/process gates. Default M1 stays on SQLite; the opt-in business service uses v4. |
| Static console runtime | nginx-unprivileged stable-alpine3.24 | Immutable content selected through the digest in images.env; serves the production-built console and proxies the local API. |
| Optional trace viewer | Jaeger 2.23.0 | Pinned local trace viewer. The Phase G lane inspects filtered native/application OTLP export; viewer availability alone remains insufficient. In-memory local traces do not establish production retention. |

Exact container references are maintained only in images.env. The
[Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) records
combined local browser/native evidence and actual runtime/browser versions. The
positive source publishes bundled PCM using WebAudio and real WebRTC, without
overriding getUserMedia; microphone permission denial is a separate actual-browser
negative. The local scripted path does not establish physical capture, human
hearing or real-provider quality. Docker Desktop on macOS arm64 is the tested local
platform. The local POC qualifies the selected macOS host and Linux containers
with actual runs. Remote CI/publication are outside scope; existing workflow
definitions are optional automation references.

### Native adapter dependency edge

The [completed native/deadline handoff](work-items/0036-native-input-and-deadline-cancellation.md)
reconfirmed the selected stable Python [Agents 1.8.11 release](https://github.com/livekit/agents/releases/tag/livekit-agents%401.8.11)
and browser [client 2.23.0 release](https://github.com/livekit/client-sdk-js/releases/tag/v2.23.0)
on 11 November 2026. The new optional channel-continuity native extra declares the
already selected Python SDK. It changes workspace dependency metadata, with no
resolved-package version changes; the browser lock and image selections are
unchanged. Default Python codec imports remain SDK-independent. Installed pinned
source and actual SDK regression tests govern compatibility; a current web page
alone cannot establish it.

The optional native page/host adapter passed its selected actual six-group native
and isolated Python/npm package gates. Final selected phase checks passed. The
Python artifacts retain six runtime payloads and the optional pinned SDK; fifty-five
unadapted local tests passed. The npm artifact retains seventy-eight current
payloads with exact public v6 PG/HTTP replay. Host SDK processes connect to the
existing Docker SFU; no new default application image,
Compose service, paid provider or inference fallback is introduced. P3's unchanged
production package is freshly built/installed for the selected deadline gate;
its compatible qualified P1 wheel is reused with current source/README parity.

## Installed application and development tooling

| Area | Exact versions | Current use |
| --- | --- | --- |
| Python environment | uv 0.13.7 | Resolve and reproduce the Python environment with uv.lock |
| Control API | FastAPI 0.162.2; Uvicorn 0.54.0 | Default M1 plus opt-in scoped business/session HTTP adapters |
| Runtime validation and database client | Pydantic 2.14.3; psycopg 3.3.8 with its binary extra | Typed HTTP contracts, restricted PostgreSQL v4 authority, controlled migrations and bounded adapters |
| HTTP client | HTTPX 0.28.1 | Local HTTP integration and API test support |
| API metrics | prometheus-client 0.26.0 | Direct pinned local dependency, isolated registry and protected bounded-label metrics |
| Python checks | pytest 9.2.0; Ruff 0.17.4; mypy 2.4.1 | Installed test/lint/type tools; reports must identify which checks actually ran |
| JavaScript package manager | pnpm 12.18.0 | Root workspace and frozen dependency resolution |
| TypeScript and Node types | TypeScript 7.0.2; @types/node 26.6.6 | Strict console compilation |
| Browser build and tests | Vite 8.3.6; Vitest 5.1.0 | Strict controller/adapter tests and production asset build; exact executed totals belong in phase evidence |
| Python build backend | setuptools 84.2.1 | Exact build-system pin in pyproject.toml |

The current packages are declared in [pyproject.toml](../pyproject.toml) and the
[console package](../apps/local-console/package.json). Installed tooling is not
an assertion that every possible lint/type check passed. Retain the executed
commands and results in local evidence.

### Frozen installed bytecode

The shared Python image runs frozen non-editable production installation with
uv --compile-bytecode during build. Installed children can reuse image caches
while runtime PYTHONDONTWRITEBYTECODE=1 prevents cache writes. This is build/runtime
preparation under the same pinned Python, dependencies and source contracts;
source/image verification and actual gates remain required. No stable speedup,
throughput or binary-reproducible archive claim follows from it.

## Dependency inventory tool qualification

No repository SBOM or vulnerability scanner is currently qualified. Before adding
one, freeze the local tool/version/configuration and exact lockfiles as a bounded
tooling slice. The current pnpm lockfile contains two YAML documents; the selected
tool must process the application importer and resolved transitive graph, not
stop after package-manager configuration. Verify known direct production and
development entries, including livekit-client and browser/build tooling, plus
known resolved transitives against the frozen lock. Cover every implemented
workspace package, including future P2/P3 importers, and the Python lock graph.

Retain positive inventory output and a negative first-document-only fixture or
intentionally incomplete inventory that the gate rejects. A zero-entry result,
missing application importer or omitted package fails inventory completeness.
Record scan freshness, advisory-database availability, exclusions and unresolved
results separately from graph coverage. Do not claim vulnerability or supply-chain
qualification from a lockfile parser alone. Dependency pins remain unchanged in
this review; upgrades require the existing intentional compatibility checkpoint.

## Future dependency candidates

The TypeScript Agents SDK candidate is @livekit/agents 1.9.5. It is not installed
in the current console/control-API foundation. Introduce it only if a selected
component hosts a Node realtime agent; then resolve and exercise its RTC/native
peers before promotion. Ordinary TypeScript HTTP specialists need typed handlers,
runtime schemas and capability/provider clients, not an additional media runtime. [Release](https://github.com/livekit/agents-js/releases/tag/%40livekit/agents%401.9.5),
[release package metadata](https://api.github.com/repos/livekit/agents-js/contents/agents/package.json?ref=%40livekit%2Fagents%401.9.5).

The explicit local_real checkpoint adds livekit-plugins-openai 1.8.11 using the
existing compatible OpenAI 3.46.0/httpx2 2.16.0 resolution. The runtime uses only
fixed private local endpoints with ambient authorization/proxy configuration
excluded. Actual local engine/model/media qualification remains pending; the
default scripted and offline lanes do not call those engines. Retain the actual
browser executable/version in local evidence.

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

## Explicit local real-inference selections

| Component | Frozen selection | Evidence boundary |
| --- | --- | --- |
| Native LLM plugin | livekit-plugins-openai 1.8.11 | Uses the selected Agents 1.8.11; no remote provider fallback |
| Local LLM | Ollama 0.40.15 with qwen3:4b-instruct Q4_K_M | Immutable engine/model declaration; actual model/tool outcomes pending |
| Local ASR | whisper.cpp 1.9.5 with base.en | Built from selected release; actual recognition quality pending |
| Local TTS | piper-tts 1.8.0, onnxruntime 1.31.1, en_US-ljspeech-medium | Separate engine process; generated-speech/media qualification pending |
| Model cache | Ten exact files, 2,708,795,741 bytes including the 859-byte Ollama manifest | Explicit fetch and checksum verification; weights being present does not establish inference |

[Model declarations](../local-setup/models/local-model-manifest.json) own exact
byte sizes/digests and public release/license sources. The
[operations guide](local-real-inference.md) owns preparation, runtime isolation,
resource ceilings and pending gates. The frozen declaration is an input snapshot;
its original status label is not rewritten when a cache or runtime check passes.

## Preserve upstream compatibility

Python Agents 1.8.11 requires Python >=3.10,<3.15, livekit==1.2.0 and
livekit-api>=1.2.2,<2. Both project distributions require Python >=3.14,<3.15 and
select 3.14.10. This narrower local support policy does not advertise every version
allowed by the upstream SDK. Python 3.15 is outside the SDK range. Preserve the upstream constraints
rather than independently forcing incompatible transitive upgrades.
[Release metadata](https://github.com/livekit/agents/blob/livekit-agents%401.8.11/livekit-agents/pyproject.toml).

For the future Node Agents integration, the selected release workspace uses an
@livekit/rtc-node range of ^1.1.0 and the Agents package declares Zod
^3.25.76 || ^4.1.8. These are compatibility constraints, not claims of an installed
Node agent. If that optional runtime is selected, native imports and actual
Node-agent tests must validate the resolved selection. HTTP specialist contract
tests remain required regardless of that dependency choice. [Release metadata](https://api.github.com/repos/livekit/agents-js/contents/agents/package.json?ref=%40livekit%2Fagents%401.9.5),
[workspace metadata](https://api.github.com/repos/livekit/agents-js/contents/pnpm-workspace.yaml?ref=%40livekit%2Fagents%401.9.5).

## Promotion gates and current evidence

| Gate | Observed foundation evidence | Remaining promotion work |
| --- | --- | --- |
| STACK-01 Versions and compatibility | Exact runtime, SDK, application, tool and image selections recorded | Refresh public metadata at each integration or upgrade |
| STACK-02 Clean resolution | uv.lock, pnpm-lock.yaml and image digests exist and support the current foundation | Add and reproduce future provider/specialist dependencies with frozen resolution |
| STACK-03 Native imports | Python SDK imports, host/container transport and selected provider_real v2 native integration exercised | Qualify additional provider/native integrations as introduced; Node Agents peers only for an actual Node realtime component |
| STACK-04 Language checks | Root/P1/P2/P3 Python correctness/typing, console app/E2E checks, P2/P3 TypeScript contract, standalone/HTTP checks and explicit P2 PostgreSQL lane | Recoverable dispatch/coordinator integration, full artifact release and media/recovery qualification |
| STACK-05 Local room | Diagnostic/M1, Phase G scripted media and selected provider_real v2 P1 browser inference/playback qualified in their declared scopes | Physical capture, local_real and P2/P3 integration/charter qualification |
| STACK-06 Local runtime parity | Selected macOS arm64 host and isolated Linux P1 installed consumers passed; Python 3.14-only metadata | Qualify P2/P3 artifacts and any newly advertised platform; no remote CI prerequisite |
| STACK-07 Retained evidence | Local smoke/build, historical H1, current full H2, selected provider media, installed packages and reviewed P1 release index retained | P2/P3 workload/media/platform evidence and optional local_real qualification for their respective claims |

The overall stack remains partially validated. P1-01 through P1-05 have executable
SQLite acceptance/recovery evidence; P1 local V1 coverage passed; complete P2/P3 product acceptance remains pending.
Use the harness catalog for current complete runner registrations. Later P1 phase contributions retain separate database/process,
browser/native and trace evidence. They do not establish P2/P3 behavior, real-model
quality, production capacity or a completed portfolio release.

## Reproducible pins and upgrades

Use exact direct pins, uv.lock, pnpm-lock.yaml, runtime version files and
versioned image references with recorded digests. A readable mutable tag is
acceptable only when the accompanying digest fixes the actual image content.
Keep secrets outside tracked configuration and diagnostics.

Hold the validated frozen baseline within each feature slice. Recheck upstream
stable direct versions at a new SDK/provider integration, intentional upgrade and
portfolio release. Version refresh is not an automatic prerequisite for unrelated
feature edits. Change pins and locks together, then rerun affected native,
contract, correctness, local-media and benchmark checks. Preserve the preceding
working environment until its replacement passes. Never relabel older evidence
as if it used a newer runtime or provider. Select stable direct dependencies and
exclude unsupported overrides. The SDK currently requires beta OpenTelemetry
transitives (including 0.66b2 instrumentation packages); uv.lock preserves those
upstream constraints. These required transitives are not a reason to override SDK
compatibility or describe every resolved package as a stable release.

## Phase G dependency checkpoint

The native consumer uses the frozen Agents 1.8.11 and browser SDK 2.23.0 pins.
OpenTelemetry API/SDK/HTTP exporter 1.45.2, already present in the SDK-compatible
lock, are explicit local direct dependencies for the new tracing consumer. Required
SDK beta transitives remain as resolved; this is not a provider/SDK upgrade.
Playwright 1.65.0 is an exact development-only dependency for isolated actual browser
media verification. pnpm 12.18.0 validates the frozen workspace lock. Local browser
runs record the installed browser version; the browser is not distributed in the
application image. No inference-provider package or implicit model download is
introduced by that historical G checkpoint. New speech assets include their local fixture provenance manifest.
Native input/status controls require actual RoomIO readiness and active SDK state.

The [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) records
the locally measured seeded inquiry baseline for S-I06 and the first P1-I27 slice.
Its declarations were frozen before measurement against the existing installed
baseline; no SDK, provider or production dependency change was needed for H1.
H2 reliability and P1-I26 host/Linux artifact/API/genuine-consumer gates passed
separately. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified; P2/P3 slices are partial and complete product release remains pending. No local fault window or configured container ceiling is a
production capacity result.

## Read-only submission and dispatch checkpoint

P3 now declares agent-continuity[postgres] 0.1.0 as an actual public library
dependency. The workspace/lock records that edge; the existing pinned SDK,
psycopg and other third-party selections are retained through offline resolution.
Its Python HTTP client uses native asyncio streams, with no added HTTP/provider
runtime dependency. P1's read-only work profile is explicitly owner-installed and
P2's dispatch schema has an explicit v1-to-v2 upgrade; neither starts a service or
migrates on ordinary import. The [phase work item](work-items/0028-p2-dispatch-and-p3-coordinator.md)
owns executed compatibility, artifact and resource evidence. Models, media and
complete P2/P3 platform/release qualification remain separate.

## P2/P3 contract and storage checkpoint

The P2 server subpath adds pure-JavaScript pg 8.23.1 and @types/pg 8.23.1;
no native driver or ORM is introduced. The source package's browser-safe codec
does not import this server path. Transaction and pool contracts were checked
against the maintained [transaction guide](https://node-postgres.com/features/transactions)
and [pool API](https://node-postgres.com/apis/pool): use one checked-out client
per transaction, bound application admission as well as connections, observe idle
client errors and close owned clients explicitly. Actual versions are frozen in
package manifests and pnpm-lock.yaml; these docs do not assert later releases.

Prettier 3.9.10 is a pinned root development tool for P2/P3 TypeScript source,
tests and public examples. It adds a root format gate while preserving the existing console source.
The P3 TypeScript policy-contract package reuses the existing TypeScript, Vitest
and Node types; its HTTP handler/client use Node built-ins with no new runtime
provider/RTC dependency. Neither package changes P1 Python production dependencies
or implicitly starts a service. The HTTP and standalone slice retains the frozen
versions; no new dependency resolution is introduced. Actual public-archive and
Node host/Linux observations belong to the
[work item](work-items/0027-p2-standalone-and-p3-http.md).
