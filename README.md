# LiveKit Agents ecosystem

Status: Active
Last reviewed: 13 November 2026

## Overview

A local-first engineering ecosystem for three reusable LiveKit agent projects.
One synthetic travel-support application demonstrates how durable execution,
conversation continuity and reliable delegation compose around native SDKs.

| Project | Responsibility | Scope |
| --- | --- | --- |
| Agent Continuity Lab | Durable execution, recovery, confirmation and supplier effects | [P1 charter](docs/projects/agent-continuity-scope.md) |
| Channel Continuity Kit | Voice/chat/SMS continuity, durable input and communication evidence | [P2 charter](docs/projects/channel-continuity-scope.md) |
| Delegation Reliability Kit | Typed specialists, bounded work, result applicability and delivery | [P3 charter](docs/projects/delegation-reliability-scope.md) |

All business accounts, bookings and supplier operations are fictional. The default
local transport lab needs no model-provider account or carrier credentials; the
explicit provider_real profile separately requires real provider accounts/keys.

## Implementation status

| Component | Current state |
| --- | --- |
| M1 investigation intake | Implemented: SQLite persistence, scoped idempotency, conflicting replay, CLI and authenticated local HTTP API |
| Development harness | Implemented: documentation/module checks, negative fixtures, acceptance discovery and baseline execution |
| Local infrastructure | Implemented: self-hosted LiveKit, PostgreSQL, control API, diagnostic SDK worker, browser console and optional Jaeger |
| Transport integration | Actual host and container native SDK text/audio checks passed; browser qualification is recorded separately |
| Showcase and API signals | Retained M1 intake/replay/conflict diagnostics plus opt-in scoped current-case observations, exact human quote approval and native scripted media; protected metrics and safe correlated logs |
| Locked dependencies | Frozen Python/pnpm resolution and registry-digest-pinned container bases |
| P1 PostgreSQL cutover | Implemented: explicit backed-up quiescence/import, restricted migration/runtime roles and scoped inquiry service; separate real PostgreSQL gate |
| P1 execution foundation | Explicit backed-up SQLite migration, typed inquiry/effect/attempt state, bounded async I/O and real intake-process acceptance tests |
| P1 inquiry worker | Independent persisted read-only fake supplier, cooperative single-worker execution and real supplier-success crash reconciliation |
| P1 authority and continuation | PostgreSQL v2 exact quotes/confirmation, atomic intent/dispatch, waits/signals and finite retry/deadline policy; standalone container demo |
| P1 supplier effects and completion | Implemented on PostgreSQL v3: exact supplier-bound proposals, mutation recovery/uncertainty, idempotent cancellation and durable completion delivery; Phase E gate passed |
| P1 coordination and worker deployment | Implemented on PostgreSQL v4 with the Phase F gate passed: server-time leases/epochs, bounded admission and an opt-in worker profile |
| P1 conversation and showcase | Default scripted native speech/tools, atomic managed intake, scoped current-case UI, exact UI approval and filtered OTLP; the [Phase G work item](docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) owns scripted evidence |
| P1 opt-in read-only work | Credential-bound immutable acceptance; explicit v2 issued attempts/results and v3 receiver-bound delivery/guarded action plus an explicit v4 scoped result feed; separate from booking v4 with no generic worker |
| P1 standalone distribution | Canonical src-layout agent-continuity package, typed inquiry/managed APIs and isolated installed examples; host/Linux isolated artifacts and genuine native consumer passed; detailed evidence belongs to the [package work item](docs/work-items/0016-p1-standalone-package.md) |
| P1 provider inference | The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. See the [provider work item](docs/work-items/0018-p1-provider-demo.md). |
| P1 local real inference | Explicit Whisper/Qwen/Piper implementation and trusted profile/readiness binding; actual engine/model/browser qualification remains pending in the [inference work item](docs/work-items/0017-p1-local-real-inference.md) |
| P2 channel kit | Verified intake, dispatch, gateway and owned scripted-agent recovery; explicit structured revision routing is qualified locally; linked exact confirmation and immutable prompts have passing selected local qualification; outbound reply intents, authorized reservation and ordinary fake-carrier sends passed selected local gates; authenticated correlated callback evidence passed its selected local gates; explicit uncertain-send policy passed its selected local source/installed gates; opt-in native text/committed voice passed selected actual native and installed-artifact gates; final selected phase gates passed |
| P3 delegation kit | Native/contracts, immutable input, P1-issued results, durable receiver acceptance/guarded action and locally qualified as-of projection metadata; explicit delivery-only processing passed selected local gates; explicit applicability refresh/display retention and protected-action races and selected deadline/cancellation schedules passed their source/installed gates; P3-01/P3-03/P3-11 have registered passing lab runners; remaining 14 rows and full release remain pending |

The default diagnostic profile echoes text and counts received audio frames; it
performs no STT, model reasoning or TTS. Original M1 routes retain SQLite. The
explicit business profile uses PostgreSQL v4 and a native AgentSession with local
scripted STT/LLM/TTS fixtures. Its browser publishes bundled spoken PCM through
WebAudio and actual WebRTC, then observes real returned audio and state. This is
local scripted-media evidence, not physical microphone or real-inference quality.
The separate local_real profile uses prepared local Whisper, Qwen and Piper
engines. It preserves the same authority and task identities; actual engine/model/
media qualification remains pending. The [conversation guide](docs/conversation-and-showcase.md)
owns shared behavior and the [local-real guide](docs/local-real-inference.md) owns
explicit model preparation and operations.
All twenty P1 rows have retained passing reports and an independently verified
local release index. Complete P2/P3 acceptance and integrated release remain pending, so the whole-ecosystem aggregate remains
incomplete. The [catalog](harness/catalog.json) owns executable registrations;
each required scenario must still be rerun when its behavior or inputs change.

See the [case/continuation guide](docs/case-and-continuation.md) and
[effects/completion guide](docs/effects-and-completion.md). Run make phase-d-demo
for the isolated Phase D backend demonstration, or make phase-e-demo for the
confirmed mutation/cancellation/completion crash proof. The
[Phase E work item](docs/work-items/0011-p1-phase-e-effects-and-completion.md)
records the supplier/cancellation/completion implementation and final gate status.
Phase F adds per-task lease authority and a pull worker whose child performs one
bounded step from persisted state. Its
[combined gate](docs/work-items/0012-p1-phase-f-leases-and-deployment.md) has
passed. The [lease/worker guide](docs/leases-and-workers.md) owns the v4 runtime contract.
Run make phase-f-demo for the isolated actual-worker restart, admission and completion proof.
The opt-in business workspace composes these capabilities; the original M1
browser/API and diagnostic room remain independently available.

### Current native-input and deadline slice

The [completed native/deadline handoff](docs/work-items/0036-native-input-and-deadline-cancellation.md) separates implemented code from
qualification. P3-I13 passed its selected source and isolated installed eighteen-case
deadline/cancellation gates and forty-six assertions across the existing execution,
applicability and action-race regressions. P1 and P3 production runtime payloads
are unchanged. New ineligible work cannot invoke a specialist or authorize an
action; late immutable facts remain readable and separately confirmed current work
still progresses.

P2-I15/I16 passed the selected six-group actual native gate: browser text, WAV
committed voice, returned text/audio, v6 restore and complete cleanup. Isolated
Python and npm artifacts passed their distinct installed gates. Focused checks
passed: fifty-five P2 Python tests, 530 P2 TypeScript tests, sixty-five browser-policy
tests and forty-five wrapper tests, plus one actual local HTTP proxy regression.
Final selected phase gates and the affected UI-hint media rerun passed, completing
P2-I15/I16 and P3-I13 within this selected scope. At that checkpoint, fast checks passed 1,788
Python checks with zero skips/violations, broad/strict typing over 141/116 files
and Python formatting over 355 files. Frontend checks passed 1,000 TypeScript tests
(392 console, 530 P2 and 78 P3), types, formatting and builds. P2 compatibility
passed 141 assertions plus one focused regression; P3 retained forty-six selected
compatibility assertions. Default-stack checks passed eight checks and ten audio
frames with M1 state preserved. Full P2/P3 rows remain planned; no catalog
registration or default deployment is added. That completed I15/I16/I13 scope
precedes the selected playback/recovery phase below.

The completed [playback evidence and process recovery slice](docs/work-items/0037-playback-evidence-and-process-recovery.md)
qualifies selected P2-I17 and P3-I14. The current phase below adds verified case
rehydration and maintained standalone consumption; full charter/release gates remain separate.

The [completed case rehydration and standalone phase](docs/work-items/0038-case-rehydration-and-standalone-release.md)
qualifies selected P2-I18 and P3-I15. P2 passed eighteen storage assertions, three
actual media groups, its 111-test Python distribution, seven npm consumer stages
and 166 compatibility assertions. P3 passed eight offline plus eight actual
installed assertions. Shared gates passed 2,148 Python and 1,224 TypeScript tests
(503 console, 632 P2 and 89 specialist), broad/strict typing over 144/132 files,
Python formatting over 387 files and documentation validation for all 113
maintained documents. All 29 Mermaid bodies passed syntax parsing; that check alone does not qualify architecture or
behavior. Ordinary doctor/smoke passed with ten audio frames and original M1 state
preserved. All 17 P2 and the remaining 14 P3 charter rows retain their own gates.

### Prior workload and image slice

The [completed handoff](docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) implements P2-I19's seeded capacity/dormancy
study and P3-I16's standalone booking.extract_document HTTP capability.
Selected local qualification passed for both tasks; prior checkpoint counts above remain
historical results. The new image path uses a bounded scripted fixture provider,
actual PNG guards and separate structural/factual checks. It provides no OCR,
real vision inference or P1 durable image execution/action authority. P2 keeps
existing v7 identities and bounds ordinary observer callbacks without changing DDL.

Final shared gates passed 2,272 Python and 1,318 TypeScript tests with zero
required skips, broad/strict typing over 146/140 files, 403-file Python formatting
and 115-document validation. All 29 Mermaid bodies passed syntax checks. Exact
workload, isolated-package, compatibility and preservation outcomes are recorded
in the completed handoff; all seventeen P2 and fourteen remaining P3 charter rows
retain their full acceptance gates.

Use make p2-workload-plan and make p3-document-plan to inspect the fixed inventories
before running the opt-in gates documented in the [local setup guide](local-setup/README.md).
### Completed operations and fixed-policy checkpoint

The [completed operations and policy handoff](docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
qualifies selected P2-I20/P3-I17. The separate operations page follows real durable
input/dispatch/reply/callback observations, bounded authenticated reads, safe errors
and real process metrics/spans. P3 adds explicit policy-v2 evaluation from separate
immutable policy/fact records, with structural parsing and factual verification.
Version 2 has a separate typed durable runner qualified in 0041; the v1 runner
and defaults remain compatible. Selected native v2 RTC text qualification passed in 0042.

P2 passed sixteen PG/HTTP groups and three actual browser groups in one case,
seven isolated npm stages over 105 payloads, and 187 fresh compatibility assertions
in eleven serial lanes. P3 passed twenty source and twenty installed fixed-policy
assertions, separate offline-eight package checks, both twenty-assertion image
regressions and 146 current policy/recovery/registered compatibility assertions.
Shared gates passed 2,370 Python and 1,439 TypeScript tests without required skips,
broad/strict typing over 148/146 files and Python formatting over 414 files.
Documentation and independent source/artifact/residual reviews are recorded in
the handoff. These are local POC qualifications, not fleet capacity or model accuracy.

The [completed standalone/durable-policy work item](docs/work-items/0041-standalone-channel-and-durable-policy.md)
implements P2-I21's installed application and P3-I18's typed durable-v2 prerequisite.
P2 passed twenty installed standalone assertions, six separate public-P1 adapter
assertions and 187 compatibility assertions. P3 passed twelve source/twelve installed
durable assertions, eight separate offline package assertions and 146 selected
regressions. Shared checks passed 2,537 Python and 1,501 TypeScript tests, broad/strict
typing over 150/156 files, formatting over 433 files and 119 documentation checks.
The handoff records exact source/archive attribution and preserved failed attempts.
The [native policy handoff](docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records responsive RTC text and the compact optional result view: twelve backend/SDK
assertions and three browser groups passed in both source and installed modes; the
installed mode also passed eight separate offline package assertions. Both runs
closed every owned process, room and disposable schema. Shared checks passed 2,590
Python and 1,580 TypeScript tests with zero required skips. Full P2/P3 acceptance,
the combined voice/text/SMS return journey, integrated provider demonstrations and
the final demo video retain their separate gates; the broader goal remains active.
No remote CI or GitHub publication is required.

## Documentation

Start with [AGENTS.md](AGENTS.md), [Design.md](Design.md), the
[portfolio scope](docs/portfolio-scope.md), [build plan](docs/build-plan.md) and
[granular phase/task roadmap](docs/implementation-plan.md). Design authoring uses
the [standard template](docs/design-template.md); Python work follows the
[engineering guide](docs/python-engineering.md).
The [architecture review disposition](docs/work-items/0020-architecture-audit-reconciliation.md)
maps the latest review to current evidence and planned operational/P2/P3 changes.
Use the [local setup guide](local-setup/README.md) for ports, credentials,
lifecycle, diagnostics and reset behavior. The [validation plan](docs/validation-plan.md),
[technology baseline](docs/technology-baseline.md), [harness guide](harness/README.md)
and [documentation standards](docs/documentation-standards.md) define the engineering
contract. The [plan audit](docs/plan-audit.md), [demo plan](docs/demo-plan.md) and
[observability contract](docs/observability.md) record the optimized delivery and
capability evidence. The [starter walkthrough](docs/project-brief.md) explains M1 behavior.

```text
apps/local-console/            Browser operator console (TypeScript)
services/control_api/          Authenticated M1/business HTTP and scoped media-invocation grants
services/rtc_agent/            Native Python Agents SDK diagnostic worker
services/conversation_agent/   Native business AgentSession and explicit inference adapters
projects/agent-continuity/python/src/continuity_lab/               M1, managed admission and PostgreSQL case/effect/delivery authority
projects/agent-continuity/     P1 standalone package, examples, design and instructions
projects/channel-continuity/   P2 TypeScript channel runtime, Python codec and optional native SDK adapter
projects/delegation-reliability/ P3 Python baseline/contracts and TypeScript specialist HTTP
contracts/                    Shared producer/consumer schema fixtures
local-setup/                   Compose, image locks, configs and lifecycle manager
harness/                       Contracts, documentation rules and acceptance catalog
tests/                         Python correctness and integration-boundary tests
docs/work-items/               Implementation plans, results and handoffs
.github/workflows/             Python, console and actual local-stack CI definition
```

The new P2/P3 Python workspace members are development dependencies for local
contract/baseline checks. The serving image retains the P1/application runtime
dependency set. Root frontend commands include the console, P2 channel package and P3 specialist
contract package; root Python checks include all three project suites. Contract or baseline
evidence alone does not complete a product row. P3-01/P3-03/P3-11 separately
have complete registered lab assertions and fresh passing reports; all 17 P2 and
remaining 14 P3 rows remain planned.

Each service, app, project and local setup area has AGENTS.md, Design.md and
README.md. Existing workflow definitions are optional automation references.
GitHub publishing and remote CI execution are outside this local POC delivery scope.

## Requirements

For the Docker route, install Docker Engine/Desktop with Compose 2+ and host
Python 3.14. Docker supplies the pinned application runtimes. Allow about 2 GB
of free Docker memory plus build/image disk space. Initial dependency/image
fetches require internet; subsequent transport checks use local services.

For current host qualification, use Python 3.14.10, Node 24.22.2 and pnpm 12.18.0.
The host .node-version matches the source/installed SDK gates. The pinned Docker
build image uses Node 26.13.0; accepting that engine line does not establish the
separate host gate on it. All Python distributions support 3.14 only
(>=3.14,<3.15); 3.14.10 is the selected host/container runtime. Full Python checks require
the frozen local, agent, inference and development dependencies. Only M1's isolated CLI/test
subset and the lifecycle manager are dependency-free.

The optional local-real profile requires an explicit 2.709 GB model fetch plus
engine/build storage and substantially more Docker CPU/memory than the diagnostic
foundation. Check the [operations guide](docs/local-real-inference.md) before
preparing it. This local-engine profile needs no paid provider or carrier account; setup/download and
actual inference qualification are distinct steps.

## Commands

From the repository root, start the complete implemented foundation:

```sh
python3.14 local-setup/stack.py init
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py start
python3.14 local-setup/stack.py smoke
```

Use the selected Python 3.14 interpreter for the manager. Open
http://127.0.0.1:13000. Retrieve the local operator token with the explicit command
below and paste it into the console password field. Credentials are generated
locally, ignored by Git and excluded from build contexts.

```sh
python3.14 local-setup/stack.py token
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py logs
python3.14 local-setup/stack.py start --observability
python3.14 local-setup/stack.py stop --observability
```

Normal stop preserves named volumes. The setup guide documents the separate,
explicit destructive reset. Host development bootstrap:

```sh
make bootstrap
npm install --global pnpm@12.18.0
pnpm install --frozen-lockfile
pnpm --filter @livekit-ecosystem/channel-continuity build
pnpm --filter @livekit-ecosystem/delegation-specialist build
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
.venv/bin/python -m continuity_lab demo
```

The SDK/gateway builds are prerequisites for cross-language Python unit checks;
those checks require the actual public JavaScript artifacts and do not skip them.
The M1 demo uses isolated temporary state. Persistent M1 CLI usage is documented in
the starter walkthrough. The stack is a loopback development deployment; production
identity, TLS/TURN, migrations, retained telemetry and capacity evidence remain
release work described in the build and validation plans.

The optional p1-workers profile is separate from normal foundation startup.
Start it only after preparing a deliberately selected ACTIVE v4 schema and its
independent supplier/receiver fixtures. The [local setup guide](local-setup/README.md)
owns start-workers, stop-workers and preserved-volume restart operations. Workers
receive only restricted runtime credentials; startup never initializes or upgrades
a supplier or database silently. The actual worker requires POSIX process ownership,
provided by Linux containers or the documented macOS/Linux host path.

The separate start-business command enables the p1-business profile only after
explicit ACTIVE v4 preparation and fixture initialization. Follow the setup guide
for its prerequisites, preserved-state shutdown and local trace configuration.
The workspace always authenticates current-case reads and keeps exact opaque
quote approval in an explicit UI command. Native hints trigger a scoped read;
model statements, playback and session End grant no mutation/cancellation authority.
The native participant must report actual RoomIO readiness and active SDK state
before input/status controls become usable. Explicit media End retires its media
context; a later Join uses a fresh room/participant/invocation for the same durable
task. Ambiguous initial connection retries preserve the frozen invocation.

The explicit provider_real profile uses Deepgram nova-3, OpenAI gpt-5.4-mini and
ElevenLabs eleven_v4_turbo. It requires three private provider keys; the default
scripted and local_real profiles do not. Follow the [provider operations guide](docs/provider-demo.md)
for setup/check/start/stop and the fresh P1-20 gate. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. Profile selection alone establishes no model result.

### Optional native/deadline checks

Run from the repository root after frozen dependency setup and the documented
local stack/restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

The first command builds the P2 SDK, then the isolated p2-native.html entry to
dist-native. It starts no service and changes no default console entry. The second
owns the selected qualified host SDK/browser/gateway exercise against local Docker
LiveKit/PostgreSQL; the third is the qualified selected P3 temporal gate. Final
phase gates and the affected media rerun after the UI hint update passed.
Scripts use ordinary local setup, never provider credentials.
The [completed handoff](docs/work-items/0036-native-input-and-deadline-cancellation.md) owns exact evidence and prerequisites.

### Stable result delivery and return context

`make p2-result-receiver-plan` and `make p2-result-receiver-check` own the selected
sixteen storage/four return assertions. Their source run passed with real P1/P2
PostgreSQL, original-receipt reconciliation and populated backup/restore.
`make p2-result-receiver-package-plan` and `make p2-result-receiver-package-check`
separately build and inspect isolated Python/npm consumers. The
[0043 work item](docs/work-items/0043-stable-result-delivery-and-return-context.md)
records their individual outcomes and preserved failures. This checkpoint qualified
the delivery/read seam. The later original-input qualification below adds the
P2/P1 origin binding; the joined voice/text/SMS demonstration follows.


### Original channel-input qualification

From the repository root, with the existing local PostgreSQL/API and pinned host
Python/Node toolchain:

```sh
make channel-origin-plan
make channel-origin-unit
make channel-origin-check
```

The selected source gate passed fourteen actual assertions across sixteen owned
process groups, with complete cleanup. It joins native/signed simulated-SMS
input to original P1 work, issued policy results and the current P2 receipt/read.
It uses three disposable schemas and one owned post-commit ACK-host kill; the
normal application and M1 record remain unchanged. Reports use fresh timestamped
paths under .local/validation/p2-channel-origin. Failed runs remain retained.

The separate make channel-origin-package-check validates built/installed public
artifacts with explicit fake ports; it does not repeat the actual database
schedule. See the [origin work item](docs/work-items/0044-origin-bound-channel-policy.md) for exact scope, failures and evidence.
Integrated browser voice/text/SMS, provider composition, restart discovery and the
final demo video remain separately gated.

### Joined application composition

The active [0045 work item](docs/work-items/0045-joined-native-channel-policy.md)
composes these qualified seams into one local application. Python owns source
listeners, public client construction and bounded background discovery/execution;
Node owns native/SMS intake, original source reads and result receipts. The private
owner profile preserves stable configuration across normal restart. Focused
component tests and independent reviews cover the implemented pieces.

Explicit owner bootstrap and a preliminary actual signed-SMS/background-result
path are working, including scoped normal-restart observations. The guarded
current-result producer and captured room attachment are component-tested. The
single-session scripted worker, Node native bridge and Python/Node prepare wire
also have scoped passing tests and independent reviews. Complete joined
qualification, the compact browser journey, providers and recording remain pending.
See the [Python application](services/channel_policy_demo/README.md) and
[Node gateway](services/channel-policy-gateway/README.md) for current boundaries.

## Validation

```sh
make check
make frontend-check
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh
```

Unprefixed deep commands retain P1-20's default local_real profile, which remains
unqualified. The qualified P1 real-profile run requires explicit provider opt-in
and all three privately configured provider keys:

```sh
P1_ACCEPTANCE_REAL_PROFILE=provider_real HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
```

If an approved public CA bundle is needed, explicitly set P1_PROVIDER_CA_BUNDLE as
described in the [provider guide](docs/provider-demo.md#explicit-local-certificate-trust).
Defaults are unchanged; provider calls require the explicit selector and keys.

The fast lane runs structural/documentation checks and all implemented offline Python
suites; make postgres-check runs the P1 real-database gate and make
p2-postgres-check runs the separate P2 lane. make p2-demo runs its two standalone
public-example/replay cases; make p3-demo runs one scripted local HTTP request with
ephemeral synthetic trust and complete owned cleanup. make p2-dispatch-check runs
the bounded v2 claim/recovery cases; make p3-coordinator-check runs actual P1-backed
submission and independent Python-to-TypeScript transport checks. make p2-gateway-check
runs actual gateway acknowledgement/forced-exit/restart tests. make p3-execution-check
runs explicit v1-to-v2 upgrade, P1-issued HTTP invocation, persisted result and
fresh-process verification. These use synthetic case/policy adapters and grant no
delivery or booking action. make p2-agent-check runs the owned scripted-agent
termination/replay subset. make p3-completion-check runs actual receiver acceptance,
fresh-process reconciliation and separately confirmed guarded fake action against
the explicitly upgraded work v3 and case v4 profiles. make check adds maintained lint and service/core type checks. Frontend checks run TypeScript,
Vitest and a production build. Smoke verifies actual dependency readiness,
authentication, M1 replay/conflict, named dispatch, text echo and fixture audio.
Run make phase-g-demo for the isolated business browser/native/trace lane after
its documented prerequisites and image/host-asset rebuilds. Its inspected result
and exact runtime/browser versions belong in the
[Phase G work item](docs/work-items/0013-p1-phase-g-conversation-and-showcase.md).
Use make p1-benchmark-plan to validate the frozen H1 workload without running it,
and make p1-benchmark for the opt-in isolated installed-service measurement. Read
the [H1 work item](docs/work-items/0014-p1-phase-h-workload-baseline.md) for its
resource limits, owned cleanup, evidence and qualification limits.
Reports belong under ignored .local. All twenty P1 rows now have registered
runners. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified; complete P2/P3 acceptance and integrated release remain pending. The P1 deep command runs actual service/media lanes with explicit
prerequisites; P2/P3 planned rows still leave those project/ecosystem aggregates
incomplete. Missing, skipped or timed-out assertions cannot pass.

The explicit make p2-routing-check lane now verifies22 equivalent standalone/P1
case-CAS assertions, including real database blocking graphs, one winning revision,
valid subsequent progress and lost-ACK uncertainty. make p3-contract-check runs
P3-03/P3-11 direct components; the registered selectors above require fresh reports.
These require the documented restricted-role local PostgreSQL/pinned Node setup.
The default stack/UI remains independent. No full P2 row, native media or new
provider/model qualification follows from these selected backend gates.

## Next milestone

P1 V1 is implemented and locally qualified with the explicitly selected
provider_real v2 profile. The [Phase H release work item](docs/work-items/0019-p1-phase-h-release-qualification.md)
records the 20-case index, current runtime/H2/PostgreSQL gates, isolated host/Linux
artifacts, shared quality and independent reviews. Preserve the original H1 and
closed phase checkpoints as historical evidence and rerun affected gates after
changes. The optional local_real profile remains unqualified under unchanged limits.

The [gateway and issued-execution checkpoint](docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
retains its original scope. The [agent recovery and completion phase](docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
adds P2-I09 owned scripted-worker recovery and P3-I07B first result delivery and
separately confirmed fake action. P1 work-profile v3 preserves accepted input and
issued results while adding immutable receiver-bound receipts and an atomic work/
case guard. A receiver receipt means accepted bytes; a current read or model result
cannot grant human confirmation. The selected gates passed, completing P2-I09 and P3-I07B; I07A plus I07B complete
the P3-I07 task. All complete P2/P3 charter and release rows retain their own requirements.
The default Docker/UI does not compose these host library/process paths. Selected
specialist/coordinator recovery and P2 playback/interruption passed in the
[completed playback/recovery handoff](docs/work-items/0037-playback-evidence-and-process-recovery.md).
Selected current-case rehydration and standalone consumption passed their local
gates. P2-I19/P3-I16 and selected P2-I20/P3-I17 passed local qualification. The
0041 work item owns current P2-I21 and the qualified P3-I18A durable prerequisite;
Selected P3-I18B RTC text qualification passed in 0042. P2-I22, P3-I19 return
routing and the broader voice/SMS showcase precede full integrated release. Selected native input and deadline proofs
are qualified separately in the completed native/deadline handoff.
The [revision-routing/acceptance phase](docs/work-items/0031-revision-routing-and-delegation-acceptance.md)
adds P2-I10 explicit expected-revision investigation routing and P3-I08 concurrent
replay/conflict, public inspection/example and first complete lab runners. P3-01,
P3-03 and P3-11 have fresh passing registered reports; 14 other P3 and all 17 P2 rows
remain planned. P2 selected routing gates and final task qualification are recorded
in that work item. I10 and I08 are complete. The [linked-confirmation/result-projection phase](docs/work-items/0032-linked-confirmation-and-result-projections.md)
implements P2-I11 linked exact confirmation and P3-I09 resumable applicability
metadata; its selected local phase qualification passed. No new full
charter row is registered. The local P1 bridge is explicit application composition; its
revision CAS has no durable command receipt, so its lost acknowledgement stays
unknown. Exact confirmation is a separate capability with an existing P1 command
receipt; explicit original-command replay can recover that known intent.
The [completed outbound-reply/processing phase](docs/work-items/0033-outbound-replies-and-completion-processing.md) implements P2-I12 durable immutable-recipient reply
intents and authorized route reservations, plus P3-I10 gap-aware completion
processing acknowledgements. Their selected local gates passed. P1 remains
unchanged; no automatic booking-completion handoff or default Compose/UI path is
added. A queued reply, provider acceptance, result receipt and processing ACK are
separate facts. Possible external calls stay unknown without a declared recovery
policy. No new complete charter row is registered.

The [completed callback/applicability phase](docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
retains selected passing P2-I13/P3-I11 evidence. Callbacks remain original-attempt
observations; refreshed applicability is non-atomic as-of metadata. Display hiding
preserves profile-lifetime replay identities and protected capacity.

The [completed send-policy/action-race phase](docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Ordinary unknown
sends remain held. Only a separately configured cooperating idempotent provider
and a new trusted controller command can reserve an eligible same-operation retry.
P3 exercises both protected revision/intent lock orders and cancellation/effect
boundaries through existing public guards. At that checkpoint, P1's 77 and P3's 30 runtime payloads,
their authorities and default Compose/UI were unchanged. No new complete charter
row, automatic retry, external provider/inference call or full-release claim follows.

The selected checkpoint passed 1,660 Python tests (49 P1, 14 P2, 238 P3,
1,359 root) and 861 TypeScript tests (326 console, 457 P2, 78 specialists), with
broad 138/strict 108 type sources and 340 files passing Ruff formatting. The
30-case P2 and 16-case P3 source gates, isolated installed consumers and prior
111 P2/101 P3 regression assertions passed. These are correctness checks, not
production capacity or real-media measurements.

Provider timestamps do not choose a winning revision. Follow dependency frontiers in the
[build plan](docs/build-plan.md) and project task plans; the whole portfolio is
not complete. Physical capture/hearing, WER, production capacity and external
provider resource/retention claims remain outside the measured local POC.

## Current playback and process recovery slice

The [current phase handoff](docs/work-items/0037-playback-evidence-and-process-recovery.md)
owns selected P2-I17/P3-I14 results and remaining gates. The optional P2 v7 profile
keeps generated text, SDK output and client playback reports separately inspectable,
with exact-response interruption and retained uncertainty. P3 recovery reconciles
original issued work/results/delivery/action through existing P1 authority after
specialist/coordinator process loss. It adds no second execution owner.

```sh
make p2-communication-check
make p2-playback-check
make p3-recovery-check
```

These local scripted/PG/process checks and isolated artifacts complement the prior
qualified P1 POC. The default M1/P1 UI, Compose and provider setup remain unchanged.
The I17/I14 handoff preserves its original scope. The completed I18/I15 work item
records current case rehydration and standalone consumption separately from broader
workload, real inference and integrated release requirements.


## Current local rehydration and standalone commands

Build the P2 package/native page with make p2-native-build, then run the explicit
local checks against the documented existing Docker PostgreSQL/SFU setup:

```sh
make p2-rehydration-check
make p2-rehydration-media-check
make p3-package-check
make p3-package-lab-check
```

The P3 default command builds and installs offline; its lab command repeats those
eight assertions plus eight actual local completion/replay assertions. The P2 media
command is an automated browser/SDK qualification that closes its owned resources.
It uses scripted STT/LLM/TTS and local fake SMS. Restored case/history/communication
are separately timed observations, and loading context creates no accepted input,
generation or business action. A later new input demonstrates continuation.

P1 revision 0 is read accurately. The existing P2 native command contract requires
positive revisions, so that state remains read only; the standalone demo uses its
legitimate revision 1 and an explicit SMS CAS to revision 2. Native continuation of
a fresh P1 revision-0 case needs a coherent versioned change before integrated
release. No automatic case revision or quote confirmation is introduced.
