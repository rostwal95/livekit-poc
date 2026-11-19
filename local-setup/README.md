# Local ecosystem setup

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to set up, run, prepare, validate and reset the isolated local Docker stack |
| Audience | Engineers who operate the stack on one development machine; coding agents |
| Scope | Setup, lifecycle, optional P1 profiles, joined showcase preparation, opt-in gates, reset and troubleshooting; excludes product requirements and design rationale |
| Owns | Local lifecycle commands, host and container networking, image pins, readiness and smoke boundaries |
| Related | [Local setup design](Design.md) · [Local setup agent rules](AGENTS.md) · [Qualification gates guide](../docs/qualification-gates.md) · [Root README](../README.md) |

## Overview

This guide is the operations manual for the isolated local Docker stack. It is for
engineers who start, prepare, validate or reset the stack on one development
machine. It covers first-time setup, the everyday lifecycle, the optional P1
business, worker and inference profiles, joined showcase preparation, the opt-in
validation gates, reset, troubleshooting and reference tables. Run every command
from the repository root.

### What the stack runs

The stack runs on Docker Desktop or a Linux Docker engine. The default
infrastructure has five services:

- a self-hosted LiveKit server;
- PostgreSQL;
- an operator control API;
- a deterministic Agents SDK (software development kit) worker;
- the browser console.

An optional profile adds a local tracing backend (Jaeger). A separate one-shot
profile prepares the P1 PostgreSQL schema. No model or carrier keys are needed for
the transport lab or the deterministic inquiry tests.

### Rules that apply everywhere

| Rule area | Rule |
| --- | --- |
| Stop | Normal stop preserves named volumes |
| Reset | Reset is a separate, destructive action that requires `--confirm RESET_LOCAL_STACK` |
| Reset | Never use reset for a normal restart |
| Configuration | Local configuration files are parsed as data |
| Configuration | Never source `.secrets.env` or other configuration as shell code |
| Credentials | Never invoke expanded Compose config to obtain credentials |
| Credentials | Never put credentials in command arguments |
| Operator token | Retrieve the operator token only with the explicit `token` command |
| Operator token | Never run the token command into shared diagnostics |
| Provider keys | Provider keys are validated privately and reach only the native runtime: the native service for P1 provider mode, or each room's native worker in the joined showcase |
| Network | Published endpoints bind only to loopback (127.0.0.1) |
| Evidence | Health, readiness, a successful plan or a configured badge is not product, media or model acceptance |
| Evidence | Missing setup, skipped tests, zero tests and timeouts never count as passing |

### Contents

| Section | What it covers |
| --- | --- |
| [Implementation status](#implementation-status) | What the default stack and the opt-in profiles provide, and what is qualified |
| [Documentation](#documentation) | Related guides and work items |
| [Requirements](#requirements) | Host software, memory, networking and the shared Python image |
| [Commands](#commands) | [First-time setup](#first-time-setup) · [Isolated stack per checkout](#isolated-stack-per-checkout) · [Everyday lifecycle](#everyday-lifecycle) (console access, logs and tracing) · [PostgreSQL role and schema preparation](#postgresql-role-and-schema-preparation) · [First persistent P1 business workspace](#first-persistent-p1-business-workspace) · [Business conversation profile](#business-conversation-profile) · [Leased durable worker profile](#leased-durable-worker-profile) · [Schema upgrades for existing schemas](#schema-upgrades-for-existing-schemas) · [Inference profiles](#inference-profiles) (local_real and provider_real) · [Joined showcase](#joined-showcase) · [Stop and reset](#stop-and-reset) |
| [Validation](#validation) | [Doctor and smoke](#doctor-and-smoke) · [Unit tests](#unit-tests) · [Explicit PostgreSQL lane](#explicit-postgresql-lane) · [P1 phase demonstrations](#p1-phase-demonstrations) · [Phase G business browser gate](#phase-g-business-browser-gate) · [Declared inquiry workloads](#declared-inquiry-workloads) · [Cooperative worker pause](#cooperative-worker-pause-in-isolated-gates) · [P2 and P3 qualification gates](#p2-and-p3-qualification-gates) |
| [Troubleshooting](#troubleshooting) | Symptoms, causes and fixes for interrupted or failed operations |
| [Reference](#reference) | Services, profiles, resource limits, image pins, published ports and report locations |
| [Next milestone](#next-milestone) | The next local-setup milestone and the work that keeps its own gates |

## Implementation status

### Default foundation profile

The default five-service profile exposes:

- the SQLite M1 intake (M1 is the original confirmed-investigation intake);
- room-scoped tokens;
- a diagnostic worker that echoes text and counts real received audio frames.

The diagnostic worker performs no speech-to-text (STT), model reasoning,
text-to-speech (TTS), SMS or specialist analysis. Normal start still serves M1 and
the transport diagnostics, and it leaves business mode off.

### Explicit P1 profiles

Explicit P1 profiles add:

- PostgreSQL v4/v5 managed admission;
- case, consent, effect and completion authority;
- database-time leases;
- an independent bounded pull worker.

The p1-business profile composes these with a scoped current-case workspace,
separate exact human quote approval, a native scripted AgentSession and filtered
local OpenTelemetry Protocol (OTLP) export. Preparing roles or a schema alone never
switches the original M1 volume or enables business mode. See the
[conversation guide](../docs/conversation-and-showcase.md) and the
[Phase G evidence](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md).

### Acceptance and qualification status

P1-01 through P1-05 retain their executable SQLite acceptance and recovery scope.
The separate PostgreSQL and phase lanes use isolated synthetic state for their
declared assertions. The harness catalog owns the current complete registrations.

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 (the fixed P1 project scope) | Qualified | For the local proof of concept (POC) using provider_real v2 ([release handoff](../docs/work-items/0019-p1-phase-h-release-qualification.md)) |
| provider_real profile | Qualified | The selected provider_real v2 gate passed both actual browser cases with cleanup ([provider work item](../docs/work-items/0018-p1-provider-demo.md)) |
| local_real profile | Not qualified | Implemented and unqualified; physical quality also remains unqualified ([local-real operations guide](../docs/local-real-inference.md)) |
| Phase H1 inquiry baseline (S-I06/P1-I27) | Qualified | Completed local measurement, recorded in the [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) |
| Phase H2 workloads | Qualified | Restart, slow-dependency, saturation and shutdown measurements passed ([H2 work item](../docs/work-items/0015-p1-reliability-workloads.md)) |
| P1-I26 package | Qualified | Host/Linux isolated artifacts, typed API and failure review, and a genuine native consumer passed ([package work item](../docs/work-items/0016-p1-standalone-package.md)) |
| P1 local release | Qualified | The current H2, host/Linux artifacts and the selected provider_real v2 local P1 release are separately qualified in the [release handoff](../docs/work-items/0019-p1-phase-h-release-qualification.md) |
| P3 lab rows P3-01, P3-03 and P3-11 | Qualified | Registered passing local lab reports ([lab runners](#revision-routing-and-registered-p3-lab-runners)) |
| All 17 P2 rows and the remaining 14 P3 rows | Planned | Complete P2/P3 acceptance and the full channel, delegation and release gates remain pending ([P2 charter](../docs/projects/channel-continuity-scope.md), [P3 charter](../docs/projects/delegation-reliability-scope.md)) |

The P1 provider results above are retained checkpoint evidence. The fresh P1-20
provider rerun after the v5 upgrade remains open in the
[qualification guide](../docs/qualification-gates.md).

### Selected P2 and P3 slices

Many P2 and P3 capabilities exist as opt-in host tooling with selected local
qualification. Ordinary Compose and console startup does not compose them. Each
work item owns exact counts, failures and evidence. Qualified means the slice's
selected gates passed; a passing selected gate does not complete a whole charter
row. The last column links the part of this guide that lists the commands.

| Capability | Status | Evidence | Commands |
| --- | --- | --- | --- |
| P2 verified PostgreSQL intake | Qualified | [0024](../docs/work-items/0024-p2-verified-durable-intake.md): explicit disposable intake lane | [Intake check](#p2-verified-postgresql-intake-check) |
| P2 standalone and P3 local HTTP examples | Qualified | [0027](../docs/work-items/0027-p2-standalone-and-p3-http.md): examples only; they do not qualify UI or media | [Examples](#p2-standalone-and-p3-local-http-examples) |
| Durable dispatch, gateway, agent recovery and completion | Qualified | [0028](../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md), [0029](../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md), [0030](../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md): disposable local qualification lanes | [Dispatch checks](#dispatch-gateway-agent-and-completion-checks) |
| P2-I10 revision routing and P3 lab runners | Qualified | [0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md): selected 22-case dual-authority gate passed | [Routing](#revision-routing-and-registered-p3-lab-runners) |
| Linked consent and result projections | Qualified | [0032](../docs/work-items/0032-linked-confirmation-and-result-projections.md): selected local qualification passed | [Linked consent](#linked-consent-and-result-projections) |
| Outbound replies and completion processing | Qualified | [0033](../docs/work-items/0033-outbound-replies-and-completion-processing.md): 24-case P2 and 16-case P3 gates and isolated installed consumers passed | [Outbound replies](#outbound-replies-and-completion-processing) |
| Callback evidence and applicability refresh (P2-I13, P3-I11) | Qualified | [0034](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md): selected local phase gates completed | [Callbacks](#callback-evidence-and-applicability-refresh) |
| Send policy and protected-action races (P2-I14, P3-I12) | Qualified | [0035](../docs/work-items/0035-send-policy-and-action-races.md): selected local gates completed | [Send policy](#send-policy-and-protected-action-races) |
| Native input and deadline cancellation | Qualified | [0036](../docs/work-items/0036-native-input-and-deadline-cancellation.md): selected native, installed-artifact and final phase gates passed | [Native checks](#native-input-and-deadline-checks) |
| Playback and process recovery (P2-I17, P3-I14) | Qualified | [0037](../docs/work-items/0037-playback-evidence-and-process-recovery.md): selected qualification recorded in the completed handoff | [Playback](#playback-and-process-recovery) |
| Current-case rehydration and standalone packages (P2-I18, P3-I15) | Qualified | [0038](../docs/work-items/0038-case-rehydration-and-standalone-release.md): selected qualification passed | [Rehydration](#current-case-rehydration-and-standalone-packages) |
| P2-I19 workload and dormancy, and P3-I16 standalone document HTTP | Qualified | [0039](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md): selected qualification passed | [Workloads](#bounded-workloads-and-standalone-image-gates) |
| P2-I20 read, error and telemetry evidence, and P3-I17 fixed-policy evidence | Qualified | [0040](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md): selected qualification passed | [Operations](#operations-and-fixed-policy-profiles) |
| P2-I21 standalone channel and P3-I18A durable-v2 policy | Qualified | [0041](../docs/work-items/0041-standalone-channel-and-durable-policy.md): selected gates passed | See the work item |
| Native real-time communication (RTC) text policy (P3-I18B) | Qualified | [0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md): selected qualification passed | See the work item |
| Stable result delivery and return context | Qualified | [0043](../docs/work-items/0043-stable-result-delivery-and-return-context.md): selected delivery and read qualification, recorded in the work item | [Result receiver](#result-receiver-qualification) |
| Original channel-input binding | Qualified | [0044](../docs/work-items/0044-origin-bound-channel-policy.md): selected source gate passed fourteen actual assertions | [Origin](#original-channel-input-qualification) |
| Joined native channel policy | Partial | [0046](../docs/work-items/0046-joined-showcase-providers-and-demo.md) records selected actual scripted/provider journeys and the video; full joined installed/container and charter qualification remains open in [0045](../docs/work-items/0045-joined-native-channel-policy.md) | [Joined showcase](#joined-showcase) |

### What ordinary startup does not compose

| Component | How ordinary startup treats it |
| --- | --- |
| P2 channel-contract codec and P3 native baseline packages | Root development dependencies, included in frozen host development setup for their explicit tests |
| Shared Python image | Copies their workspace build metadata for frozen lock validation; installs only the existing application and P1 production dependencies, with no development group |
| Console image | Sees the P2 manifest for frozen workspace resolution and builds only the console |
| P2's bounded gateway and owned scripted-agent process, and P3's issued runner, delivery and action clients | Remain opt-in host library or process paths; ordinary Compose and console startup does not compose them |
| P1 work-profile owner upgrades | Explicit and separate from the P1 booking schema v4: v2 adds issued execution, v3 delivery and action, and v4 the result feed |
| Serving code | Performs no schema-changing statements (data definition language, DDL) |
| Guarded work and case actions | Require the same supported PostgreSQL target, with separately verified schema and credential bindings |
| Independent result receiver | Owns private local receipt storage, not execution state |
| Explicit P2 case bridge | Local application composition that uses preconstructed credential-bound P1 clients and finite trusted mappings |
| Explicit P2 case bridge side effects | Loads no configuration or credentials and starts no listener on import; adds no P1 schema, runtime or dependency change and no integrated case copy |
| P2 or P3 services, model downloads and provider calls | None starts implicitly |

## Documentation

Read [AGENTS.md](AGENTS.md) and [Design.md](Design.md) in this directory first.
Then use these documents:

| Document | Purpose |
| --- | --- |
| [Ecosystem scope](../docs/portfolio-scope.md) | V1 boundaries, execution modes and release definitions |
| [Build plan](../docs/build-plan.md) | Work-package sequence and dependencies |
| [Technology baseline](../docs/technology-baseline.md) | Versions, compatibility and update policy |
| [Validation plan](../docs/validation-plan.md) | Test lanes, fault scenarios and evidence rules |
| [Qualification gates guide](../docs/qualification-gates.md) | A summary of the opt-in checks, optional profiles and acceptance runners |
| [Phase C work item](../docs/work-items/0009-p1-phase-c-postgres-cutover.md) | Actual PostgreSQL validation results and remaining limits |
| [Conversation guide](../docs/conversation-and-showcase.md) | The business profile demo |
| [Case and continuation guide](../docs/case-and-continuation.md) | Phase D setup, exact confirmation, deadline and cleanup behavior |
| [Effects guide](../docs/effects-and-completion.md) | Phase E identities, confirmation, uncertainty, cancellation and retained receipts |
| [Lease and worker guide](../docs/leases-and-workers.md) | Exact worker-profile semantics and the schema upgrade sequence |
| [Local-real operations guide](../docs/local-real-inference.md) | Model commands, model and image preparation, browser setup, resource headroom and inference limits |
| [Provider operations guide](../docs/provider-demo.md) | Provider setup, check, start and stop, and the provider acceptance selector |
| [Observability contract](../docs/observability.md) | Protected metrics, measurement semantics, cap-versus-usage and clock rules |
| [P2 operations guide](../projects/channel-continuity/OPERATIONS.md) | Variables for the optional operations page |

Image versions and registry digests are recorded in [images.env](images.env) and
[images.lock.json](images.lock.json); [Image pins](#image-pins) summarizes them.
Each gate section under [Validation](#validation) links the work item that records
its exact prerequisites and evidence.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python runtime | The selected Python 3.14 runtime | Runs the dependency-free lifecycle manager (`stack.py`) |
| Docker Engine and Compose | Compose 2+ | Needed for every stack operation |
| Frozen root environment | `.venv` from `make bootstrap`, as described in the [root README](../README.md) | Host-side tests, business preparation and the opt-in gates |
| Host Node, pnpm and browser | pnpm 12.18.0, a supported host Node runtime and the pinned Playwright-managed Chromium | The optional actual browser gates only; see [Prepare host browser tools](#prepare-host-browser-tools) |
| Host toolchain for workload and image gates | The frozen Python 3.14.10 and Node 24.22.2 | The [workload and image gates](#bounded-workloads-and-standalone-image-gates) |
| Free Docker memory | Roughly 2 GB for the core lab | Existing workloads need their own capacity; optional profiles add more ([Resource limits](#resource-limits)) |
| Disk space | Not specified | Needed for images and builds |
| Internet access | Required for initial builds | After images and dependencies are available, the transport lab uses local services |

Docker builds supply pinned Python and Node runtimes. Host Node and LiveKit
installations are unnecessary for the core Docker route.

### Networking

Defaults bind every published endpoint to loopback. The
[published ports](#published-ports) table lists them.

| Topic | Behavior |
| --- | --- |
| Published address | The local manager fixes it to 127.0.0.1 to match token URLs and the browser connection policy |
| Host ports | Remain configurable |
| Signalling URLs | The browser and container signalling URLs differ |
| Media candidates | Interactive Connectivity Establishment (ICE) configuration preserves loopback and internal candidates, so actual browser and container media must be tested |
| Host networking | No Linux-only host-network mode is assumed |
| Remote access | Local area network (LAN) and mobile access, and remote TLS and TURN (Traversal Using Relays around NAT), are separate deployment work |
| Metrics | The control API also exposes a bearer-protected `/api/metrics` endpoint; see the [observability contract](../docs/observability.md) |

### Shared Python image and bytecode

The shared [Python image](docker/python.Dockerfile) installs frozen production
extras and the workspace without editable imports. Its build stage uses uv sync
with --compile-bytecode. The runtime retains those installed caches and keeps
PYTHONDONTWRITEBYTECODE=1, so child processes do not need to write caches at
startup.

Rebuild the shared image after relevant Python or dependency changes, before actual
workload or media gates. Bytecode changes import preparation only. It does not
change business authority, model selection, worker concurrency or operation
deadlines. Retain image and source provenance. Precompiled bytecode is not a
throughput or stable latency guarantee.

## Commands

Run every command from the repository root. Lifecycle commands use the selected
Python 3.14 interpreter (`python3.14`). Host-only preparation uses the frozen
`.venv/bin/python` interpreter where a section shows it.

| Task | Command | Notes |
| --- | --- | --- |
| Create settings and private credentials | `python3.14 local-setup/stack.py init` | Run first; see [What init does](#what-init-does) |
| Check prerequisites | `python3.14 local-setup/stack.py doctor` | Before a fresh start; see [Doctor and smoke](#doctor-and-smoke) |
| Validate the Compose configuration | `python3.14 local-setup/stack.py config` | Prints no expanded secrets |
| Start the core lab | `python3.14 local-setup/stack.py start` | Bounded build, then waits for health and readiness |
| Show stack status | `python3.14 local-setup/stack.py status` | Part of [first-time setup](#first-time-setup) |
| Run the transport smoke | `python3.14 local-setup/stack.py smoke` | End browser sessions first |
| Retrieve the operator token | `python3.14 local-setup/stack.py token` | Never run it into shared diagnostics; see [Open the console](#open-the-console) |
| Show recent logs | `python3.14 local-setup/stack.py logs` | Redacted, bounded tail; see [Everyday lifecycle](#everyday-lifecycle) |
| Show one service's logs | `python3.14 local-setup/stack.py logs --service rtc-agent` | `--service` is valid only for `logs` |
| Start with the tracing UI | `python3.14 local-setup/stack.py start --observability` | Verifies that the tracing UI returns HTTP 200 |
| Stop, including the tracing UI | `python3.14 local-setup/stack.py stop --observability` | Preserves named volumes |
| Run a separate stack per checkout | Set `STACK_PROJECT` and the port variables, then run `init` | See [Isolated stack per checkout](#isolated-stack-per-checkout) |
| Prepare database roles | `python3.14 local-setup/stack.py prepare-postgres` | After init and start; never rotates a password |
| Install a staging schema | `python3.14 local-setup/stack.py migrate-postgres` | Staging only; see [PostgreSQL role and schema preparation](#postgresql-role-and-schema-preparation) |
| Prepare the persistent P1 workspace | `.venv/bin/python local-setup/stack.py prepare-business` | Host-only; `make business-setup` runs the same action; see [First persistent P1 business workspace](#first-persistent-p1-business-workspace) |
| Initialize worker fixtures | `python3.14 local-setup/stack.py init-worker-fixtures` | Use the same `P1_WORKER_SCHEMA` and `P1_WORKER_SCOPE` as preparation and runtime |
| Start the business profile | `.venv/bin/python local-setup/stack.py start-business` | Needs a prepared ACTIVE v4/v5 schema and fixtures; see [Business conversation profile](#business-conversation-profile) |
| Stop the business profile | `python3.14 local-setup/stack.py stop-business` | Drains workers with a 35-second grace period; volumes remain |
| Start the worker profile | `python3.14 local-setup/stack.py start-workers` | After explicit ACTIVE v4/v5 preparation; see [Leased durable worker profile](#leased-durable-worker-profile) |
| Show worker status | `python3.14 local-setup/stack.py worker-status` | Also the last step of the business workspace preparation |
| Show worker logs | `python3.14 local-setup/stack.py logs --service p1-worker` | See [Operate the worker](#operate-the-worker) |
| Stop the worker profile | `python3.14 local-setup/stack.py stop-workers` | Normal stop preserves all three volumes |
| Upgrade an existing schema | `upgrade-postgres`, `upgrade-effects`, `upgrade-coordination`, `upgrade-retry-pacing` | Owner-only; see [Schema upgrades for existing schemas](#schema-upgrades-for-existing-schemas) |
| Prepare and run local-real inference | `models-fetch`, `models-verify`, `start-models`, `stop-models`, `start-local-real`, `stop-local-real` | Owned by the [local-real operations guide](../docs/local-real-inference.md); see [Inference profiles](#inference-profiles) |
| Set up and run provider inference | `make provider-setup`, `make provider-check`, `make provider-start`, `make provider-stop` | Owned by the [provider operations guide](../docs/provider-demo.md) |
| Prepare a joined showcase profile | `make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=<new directory>` | Needs the started stack and `prepare-postgres`; see [Joined showcase](#joined-showcase) |
| Inspect the owner setup plans | `make channel-policy-setup-plan`, `make channel-policy-python-plan` | Inert: no database, room, model or carrier call |
| Inspect the scripted launcher plan | `make channel-policy-launch-plan` | A successful plan is not runtime readiness |
| Run the scripted launcher | `serve --profile ABSOLUTE_OWNER_CONFIG --node ABSOLUTE_NODE_EXECUTABLE` | Launcher command-line interface; add `--no-ui` for the backend-only composition; see [Scripted launcher](#scripted-launcher) |
| Start the joined showcase in provider mode | `make channel-policy-demo-start-provider` | Passes the keys only to each room's native worker; the [root README](../README.md) covers joined startup |
| Install the managed browser | `make browser-setup` | Starting a gate does not download a browser; see [Prepare host browser tools](#prepare-host-browser-tools) |
| Build the host console distribution | `corepack pnpm --filter @livekit-ecosystem/local-console build` | Rebuild after console source changes |
| Stop the stack | `python3.14 local-setup/stack.py stop` | Removes this project's containers and network and preserves named volumes; see [Stop and reset](#stop-and-reset) |
| Reset the stack (destructive) | `python3.14 local-setup/stack.py reset --observability --confirm RESET_LOCAL_STACK` | Deletes only this project's volumes and synthetic state; never use it for a restart |

The sections below give each procedure, with runnable command blocks.

### First-time setup

```sh
python3.14 local-setup/stack.py init
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py config
python3.14 local-setup/stack.py start
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py smoke
```

[Doctor and smoke](#doctor-and-smoke) describes what those two checks cover.

#### What init does

- Creates the ignored `.env` file and the private, mode-0600 `.secrets.env` file.
- Renders a secret-free LiveKit configuration under `.generated`.
- Upgrades credentials to credential schema v2. The upgrade atomically adds
  POSTGRES_MIGRATION_PASSWORD to the complete known v1 inventory. All five existing
  values, custom endpoints and the volume-owner identity stay unchanged.
- Repeated init preserves the upgraded file.
- Unknown or incomplete schemas, unsafe files and concurrent initialization fail
  before any credential is replaced.

Other actions require this explicit upgrade and do not generate missing secrets.

#### What config and start do

`config` validates the Compose configuration without printing expanded secrets.
`start` runs a bounded build and then waits for health and readiness. The lifecycle
manager checks ownership before it changes anything:

- checkout ownership, before it mutates existing containers with the same name;
- credential-derived owner labels, before it reuses or deletes persistent volumes.

Retain private local credentials with their volumes. Regenerating credentials does
not adopt existing data.

### Isolated stack per checkout

Set these values in local-setup/.env to give a checkout its own stack:

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `STACK_PROJECT` | `livekit-agent-ecosystem` | Lowercase letters, digits and hyphens; 3–41 characters | Gives the checkout its own Compose project, container, volume and image names |
| `UI_PORT`, `API_PORT`, `LIVEKIT_HTTP_PORT`, `LIVEKIT_TCP_PORT`, `LIVEKIT_UDP_PORT`, `POSTGRES_PORT` and `JAEGER_UI_PORT` | See [Published ports](#published-ports) | Host ports that do not conflict | Also change them when another stack already uses the defaults |

The lifecycle manager mutates only containers labelled for the current checkout and
project, so a second stack never touches the first. Run init before start in the
new checkout; it generates separate credentials.

### Everyday lifecycle

#### Open the console

Open the browser console (see [published ports](#published-ports)) and retrieve
the operator token explicitly:

```sh
python3.14 local-setup/stack.py token
```

Paste the token into the console's password field. The token stays in browser
memory. It is not embedded in the build or saved to browser storage. Never run the
token command into shared diagnostics.

In the console, connect to a lab room and send text. Enable the microphone only
with its explicit button. The agent returns deterministic diagnostics rather than
an AI answer.

#### Logs and optional tracing

```sh
python3.14 local-setup/stack.py logs
python3.14 local-setup/stack.py logs --service rtc-agent
python3.14 local-setup/stack.py start --observability
python3.14 local-setup/stack.py stop --observability
```

Log output retains a redacted, bounded tail from stdout and stderr. When the
combined tail obscures one service's events, select a known service, for example
with `logs --service rtc-agent`. The `--service` option is valid only for `logs`,
and selecting a service does not increase the output budget.

The optional observability profile verifies that the tracing UI returns HTTP 200.
The tracing backend uses in-memory storage. The explicit business profile also
exports filtered application and native traces. UI readiness alone does not
establish export coverage or retained production telemetry.

Normal stop and reset are described in [Stop and reset](#stop-and-reset).

### PostgreSQL role and schema preparation

After init and start, run the same commands for a fresh or a retained database:

```sh
python3.14 local-setup/stack.py prepare-postgres
python3.14 local-setup/stack.py migrate-postgres
```

#### Role preparation with prepare-postgres

- `prepare-postgres` runs a bounded bootstrap inside the existing PostgreSQL
  container, after its normal TCP server is healthy.
- The bootstrap administrator stays inside that container.
- The bootstrap creates the restricted continuity_migrator login when it is absent,
  and it checks managed role attributes.
- It verifies both retained passwords through TCP authentication with the Salted
  Challenge Response Authentication Mechanism (SCRAM).
- It resumes an interrupted pending creation. It refuses an existing credential or
  policy mismatch without rotating a password.
- Start alone does not perform this role operation.

#### Staging schema with migrate-postgres

`migrate-postgres` runs the p1-migrate service of the optional migrations profile
once, with only the migration credential. The bootstrap administrator stays inside
the PostgreSQL container, and the other processes receive these credentials:

| Process | Credentials it receives |
| --- | --- |
| p1-migrate (one-shot migration) | Only the migration credential |
| Serving API | The existing runtime password |
| Agent | Neither migration nor bootstrap credentials |

The runtime role cannot create schemas or tables, use temporary tables or change
migration metadata. The migration role has CONNECT and CREATE on livekit_lab. The
versioned schema command installs application table ownership and grants.

This command prepares a **staging schema only**. It does not import a source,
activate the target, mount the M1 application volume or switch the serving API.
Standalone cutover requires an explicit source path, a private backup and the
ordered procedure: quiesce, import, verify, source checkpoint and activation. For
an isolated executable demonstration, use `make postgres-check` (see
[Explicit PostgreSQL lane](#explicit-postgresql-lane)) and preserve the live M1
volume. Do not source .secrets.env or invoke expanded Compose config to obtain
credentials.

### First persistent P1 business workspace

Run this after `make bootstrap` and the ordinary init and start commands. Docker
must be running. This host-only preparation uses the frozen .venv interpreter and
the validated private local settings. Do not source secrets or put credentials in
arguments.

```sh
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-business
.venv/bin/python local-setup/stack.py worker-status
```

#### Prepare the authority with prepare-business

`prepare-business` is an explicit owner operation for the configured
P1_WORKER_SCHEMA. `make business-setup` runs the same action. Its host work
deadline is 90 seconds inside a 120-second owned child supervisor. On failure it
retains private recovery artifacts and reports a fixed stage and code. Reset is not
a recovery step.

For a fresh, empty target, prepare-business:

1. creates a separate empty SQLite inquiry source under the ignored private
   .local/business-bootstrap directory and preserves its backups;
2. runs the actual quiesce, import, verify, checkpoint and activation protocol;
3. applies v2, v3 and v4 in order, and takes the additive v5 step (persisted
   mutation retry due time).

It protects existing state:

- The original application_data/intake.sqlite3 M1 database is never its source.
- It neither switches the M1 API backend nor creates supplier fixtures or consent.
- An existing valid ACTIVE v4 target receives the additive owner v5 upgrade, and
  an existing ACTIVE v5 target is only checked. Neither imports the old source
  over current business rows.
- Conflicting, nonempty or unowned staging state is refused. Inspect and retain
  that state rather than deleting it to force startup.
- For recovery, retain the whole private bootstrap folder, the source, the backups
  and the existing credentials.
- Do not replace the source or change the selected endpoint or schema during an
  unfinished preparation.

The final report names the schema action in `schemaActivation`:

| Value | Meaning |
| --- | --- |
| `explicit_empty_bootstrap` | A fresh, empty target received the bootstrap described above |
| `owner_upgrade_v5` | An ACTIVE v4 target received the owner v5 upgrade, so the step was not read-only |
| `read_only_ready` | An ACTIVE v5 target was checked without change |

#### Initialize fixtures with init-worker-fixtures

`init-worker-fixtures` separately creates the same-scope synthetic supplier and
completion receiver in the retained worker_data volume. Repeating it preserves
their provider and receiver identities and the existing booking state. It does not
grant mutation consent.

Use the same P1_WORKER_SCHEMA and P1_WORKER_SCOPE for preparation, fixtures and
runtime. The defaults are continuity and demo-traveller. Normal start and stop
preserve these named volumes and accepted work.

#### Local real inference variant

For local real inference, complete this same authority and fixture setup,
explicitly prepare the pinned model cache, and use start-local-real in place of
start-business. Follow the [local-real operations guide](../docs/local-real-inference.md)
for exact model and image preparation, browser setup, resource headroom and
inference limits. The cache and healthy engines alone do not qualify actual
inference or media.

#### What this preparation does not replace

- migrate-postgres remains the staging-only schema command for explicit migration
  work. It is not a substitute for prepare-business.
- The PostgreSQL and phase demonstrations create and clean their own isolated
  schemas. Passing them does not prepare the normal persistent workspace.
- Existing older ACTIVE schemas with application data retain their original
  controlled migration history and explicit ordered upgrade procedure (see
  [Schema upgrades for existing schemas](#schema-upgrades-for-existing-schemas)).
  They must not be replaced with the empty bootstrap source.

### Business conversation profile

The explicit p1-business profile adds a named native scripted conversation agent.
Its manager commands are start-business and stop-business. Normal start leaves
business mode off.

#### Authority rules

- The primary workspace shows current persisted business facts. Retained M1
  diagnostics remain separate.
- Every current-case read is authenticated.
- Quote preparation is a read-only supplier inspection followed by authoritative
  publication.
- Exact confirmation is an explicit UI command that uses the unchanged opaque
  canonical proposal.
- Native hints, model text, output playback, Interrupt and End do not grant
  mutation or cancellation authority.

#### Prerequisites and preflight

Before starting, prepare an ACTIVE PostgreSQL v4/v5 schema through the explicit
[business preparation](#first-persistent-p1-business-workspace). Then run
init-worker-fixtures for the same P1_WORKER_SCOPE. The read-only preflight checks
the schema, the runtime role and the existing independent provider and receiver
fixtures. It does not migrate, create fixtures or grant consent.

#### Start and stop the profile

start-business builds the shared Python image. It then starts Jaeger, p1-worker,
conversation-agent and the API with business mode explicitly enabled.

- The API mounts worker_data at /business read-only.
- The native worker has no supplier mount, operator bearer or migration
  credentials.
- Scope and schema reuse the validated optional worker configuration.
- The manager supplies the fixed local Jaeger endpoint. It does not accept arbitrary
  ambient P1_BUSINESS_ENABLED values or trace destinations as configuration.

stop-business drains workers with a 35-second grace period and returns the API to
ordinary M1 mode. Volumes remain. Full stop and reset include optional profiles,
and reset remains the separate explicit destructive operation.

After draining, stop-business and stop-local-real remove the native
conversation-agent container, because a stopped container keeps its
environment, including earlier provider keys. start-business recreates it.

The configured core aggregate is 1,792 MiB. Business mode adds 256 MiB for the
durable worker, 512 MiB for the native conversation and 256 MiB for Jaeger, for
2,816 MiB of configured limits before Docker, build and browser resources. Actual
usage and production sizing need measurement.

#### API recreation and the console proxy

Both commands recreate the API container, which may get a new network address
while the console keeps running. The console's nginx proxy therefore resolves
`control-api` per request through Docker's embedded DNS, re-resolving at most every
10 seconds. A static upstream would keep the address resolved at console startup
and time out every business call after such a recreation.

#### Demo and qualification

Use the [conversation guide](../docs/conversation-and-showcase.md) for the demo.
Use `make phase-g-demo` for isolated actual browser, container and trace
qualification, as described in [Phase G business browser gate](#phase-g-business-browser-gate).

### Leased durable worker profile

Normal start still starts M1 and the transport diagnostics. The opt-in p1-workers
profile adds the actual P1 worker with an independent worker_data fixture volume.

#### Worker configuration

Optional non-secret .env values select the target:

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `P1_WORKER_SCHEMA` | `continuity` | Validated by `stack.py` | Selects the worker and migration schema |
| `P1_WORKER_SCOPE` | `demo-traveller` | Validated by `stack.py` | Selects the trusted worker scope |

Existing configuration remains valid and credentials are retained. These values do
not change the live M1 SQLite backend or activate a source automatically.

#### Prepare the target schema

- For a fresh persistent workspace, first follow the
  [business preparation](#first-persistent-p1-business-workspace). prepare-business
  takes the additive v5 step.
- For an intentionally activated v3 target, run upgrade-coordination to install
  v4, then upgrade-retry-pacing for v5 (persisted mutation retry due time). See
  [Schema upgrades for existing schemas](#schema-upgrades-for-existing-schemas).
- A fresh migrate-postgres target is STAGING and cannot start a worker.

#### Operate the worker

After explicit ACTIVE v4/v5 preparation or the existing controlled upgrade, use these
operations:

```sh
python3.14 local-setup/stack.py init-worker-fixtures
python3.14 local-setup/stack.py start-workers
python3.14 local-setup/stack.py worker-status
python3.14 local-setup/stack.py logs --service p1-worker
python3.14 local-setup/stack.py stop-workers
```

- Fixtures are synthetic supplier and completion-receiver files, explicitly
  created as the runtime user.
- Fixture initialization neither installs nor activates PostgreSQL.
- Keep the fixtures with their named volume so provider and receiver identity and
  receipts survive normal restart.
- The worker has no migration or bootstrap credential, no HTTP port and no Docker
  socket.
- Stop and reset include the opt-in profile. Normal stop preserves all three
  volumes: application, database and worker.
- Reset remains destructive and requires its existing explicit confirmation.

[Phase F leased worker demo](#phase-f-leased-worker-demo) describes the isolated
demonstration of this profile. The [lease and worker guide](../docs/leases-and-workers.md)
defines the exact semantics.

### Schema upgrades for existing schemas

Existing standalone schemas move forward only through explicit owner-only
operations. The [lease and worker guide](../docs/leases-and-workers.md) shows the
exact command sequence.

| Action | Eligible source | Result | Notes |
| --- | --- | --- | --- |
| migrate-postgres | New target | STAGING v1 | Initial v1 preparation only. A STAGING target cannot start a worker. |
| upgrade-postgres | ACTIVE v1 | v2 | STAGING is refused. The live M1 API backend is not switched. |
| upgrade-effects | ACTIVE v2 | v3 | Staging is refused. First upgrade ACTIVE v1 with upgrade-postgres. |
| upgrade-coordination | Intentionally activated v3 | v4 | Refuses unmanaged running legacy inquiries. Reconcile them on v3 first. |
| upgrade-retry-pacing | v4, after upgrade-coordination | v5 (persisted mutation retry due time) | prepare-business takes the same additive step. |

These operations do not activate or import a source and do not switch the API.
Keep schema backups and migration credentials with the documented isolated
operator procedure. Existing older ACTIVE schemas with application data retain
their original controlled migration history; never replace them with the empty
bootstrap source.

### Inference profiles

#### Trusted inference modes

The trusted native mode is exactly one of scripted (the default), local_real or
provider_real. Ordinary start and start-business retain their diagnostic and
default-scripted behavior. The local_real and provider_real implementations exist;
[Acceptance and qualification status](#acceptance-and-qualification-status) records
which one is qualified.

#### Local-real inference

The [local-real operations guide](../docs/local-real-inference.md) owns these
commands: models-fetch and models-verify, start-models and stop-models, and
start-local-real and stop-local-real.

- No start action fetches weights, installs a schema or initializes business
  fixtures.
- Ten pinned model files total 2,708,795,741 bytes. Their sizes and checksums are
  checked before engines start.
- Models are an ignored host cache, not image or build inputs.
- Runtime engines use an internal network with no host ports and read-only model
  mounts.
- The model-service ceilings add 5.5 GiB and 10 CPU to the configured business
  stack. The core-only 2 GiB guidance is insufficient for this profile.

Actual headroom and engine, model and browser qualification remain separate
measurements. A successful fetch, readiness check or configured badge is not model
or media acceptance. Prepare the workspace as described in
[Local real inference variant](#local-real-inference-variant).

#### Provider inference

The provider profile needs no local engines or model cache. Its authoritative
[operations guide](../docs/provider-demo.md) documents `make provider-setup`,
`make provider-check`, `make provider-start`, `make provider-stop` and the explicit
`P1_ACCEPTANCE_REAL_PROFILE=provider_real` acceptance selector.

- All three keys are validated privately and forwarded only to the native service.
- If start-provider fails after serving begins, the manager runs the stop-provider
  cleanup and reports
  `{"status":"failed","code":"provider_start_failed","stage":"serving","cleanup_incomplete":<bool>}`.
- local-setup/.env.providers.example lists the three key names.
- The persistent ACTIVE v4/v5 workspace and fixtures remain separate explicit
  prerequisites.
- The selected provider_real v2 gate passed both actual browser cases with cleanup.
- The joined showcase reuses the same private file.
  `make channel-policy-demo-start-provider` reads it with the strict loader and
  passes the keys only to each room's native worker.

### Joined showcase

The [root README](../README.md) covers starting the joined showcase, provider mode
and recording. This section covers profile preparation, the owner setup tool and
the scripted launcher.

#### Prepare a showcase profile

`make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=<new directory>` runs two
owner steps:

1. `channel_policy_setup.py prepare` creates the profile's disposable schemas and
   private configuration.
2. `associate-sms` links the fixed synthetic SMS sender with a signed LINK
   challenge, so simulated SMS is accepted.

Both steps need the stack started and `prepare-postgres` done. A profile holds
sixteen inputs, so prepare a new directory for each fresh demonstration.

New profiles persist an 8,000 ms dispatch claim lease, longer than the joined
gateways' 5,000 ms dispatch step deadline, so a receipt returned near that
deadline still passes the claim guard. Profiles prepared earlier keep 5,000 ms.

#### Owner setup tool and plans

The active [joined work item](../docs/work-items/0045-joined-native-channel-policy.md)
adds an explicit owner setup tool for three fresh isolated schemas and private
configuration. Inspect its inert plans from the repository root:

```sh
make channel-policy-setup-plan
make channel-policy-python-plan
```

Plan commands create no database, room, model or carrier call.

- The owner tool uses the existing local infrastructure settings. Provider keys are
  outside this setup path.
- Runtime configuration contains no migration credential. Node receives its
  separate role environment.
- The prepared profile preserves real case, task and receiver identities, a stable
  app owner and supported synthetic evidence.
- An existing target directory is rejected.
- Partial failures retain private journals. Normal serving and stop never reinstall
  or reset state.

Current status:

- Actual fresh-schema setup now succeeds, with separate read-only version,
  receiver, case and original-M1 checks.
- New preparations also publish the nonsecret specialist configuration after
  validating shared evidence identities.
- The work item records a preliminary signed-SMS, execution and delivery path and
  scoped normal restarts. They do not complete the final frozen integration gate.
- The room-bound current-result transport and Parent components are implemented.
  [0046](../docs/work-items/0046-joined-showcase-providers-and-demo.md) records
  selected connected scripted/provider journeys; full joined qualification
  remains open.

#### Scripted launcher

The explicit scripted launcher consumes an already prepared private profile and a
prebuilt gateway, specialist and joined UI. It runs no build, install, migration,
reset, sender association or provider loader. Inspect its inert plan first:

```sh
make channel-policy-launch-plan
```

Its command-line interface is
`serve --profile ABSOLUTE_OWNER_CONFIG --node ABSOLUTE_NODE_EXECUTABLE`. Add
`--no-ui` for the backend-only process composition. Actual joined startup and media
qualification retain their separate gates; a successful plan is not runtime readiness.

The optional UI uses the prebuilt public Vite preview at
http://127.0.0.1:5179/channel-policy.html. The launcher prints only the private
operator-key file path; enter that key explicitly into the page. Keys remain out of
URLs, browser storage, child arguments and diagnostics.

The showcase build links its landing page to the P1 console through the
Makefile's `P1_CONSOLE_URL`. It reads only `UI_PORT` from the non-secret `.env`
settings and falls back to 13000.

Shutdown and restart behavior:

- A normal SIGINT or SIGTERM starts UI close and Parent preparation independently.
  Preparation drains operator, room and SMS owners while application origins and
  gateway dispatch remain available. The launcher then observes gateway dispatch
  quiescence, closes the Parent application, and finally closes/reaps gateway and
  specialist. Product data is preserved. SIGHUP and SIGQUIT are treated like SIGTERM.
- Room End first fences native intake and drains the original accepted inputs
  while their grant and dispatch dependencies remain available. The original room
  owner automatically reobserves only `cleanup_incomplete` within its configured
  30-second default cleanup window. That window limits new attempts and does not
  cancel actual work. An unresolved room stays Closing; an explicit retry retains
  the original End identity.
- A native drain inspects at most sixteen total account-history rows before
  filtering the original binding, and has a 20-second retry-admission window.
  Overflow, blocked/exhausted input, unresolved receipts or expired/revoked
  authority can keep cleanup incomplete. Reobservation cannot issue a new grant
  or replace a business operation.
- The private operator key and the fixed bridge configuration survive normal
  restart.
- Only the exact original active marker is removed, after owned work settles.
- Unresolved cleanup retains the original owners and the marker. The launcher
  reobserves cleanup automatically; another signal only wakes the current wait.
- When cleanup is incomplete, the launcher prints `cleanup_incomplete` once and
  keeps reobserving the same cleanup until it succeeds. After the 120-second shutdown
  deadline each attempt fails at once, so retries without a new signal back off
  from 0.1 s, doubling to 5 s. Another signal ends the wait early.
- An existing active marker fails closed. There is no automatic crash recovery or
  destructive repair.

### Stop and reset

Normal stop removes this project's containers and network and preserves named
volumes. Full stop and reset include the optional profiles. Normal stop preserves
all three volumes: application, database and worker.

Reset is intentionally separate:

```sh
python3.14 local-setup/stack.py reset --observability --confirm RESET_LOCAL_STACK
```

- Reset deletes only this project's volumes and synthetic state.
- Never use reset to perform a normal restart.
- Reset is not an upgrade procedure, and it is not a recovery step for a failed
  business preparation.
- Changing database credentials on an initialized volume requires a separate
  explicit role and password operation.
- Init upgrades only the known credential inventory. Neither role preparation nor
  normal restart rotates existing passwords.

## Validation

The validation lanes are separate. Offline unit tests cannot substitute for the
actual PostgreSQL, browser or media gates. Missing setup, failures, skipped tests,
zero tests, timeouts and incomplete cleanup never count as passing. Keep actual
PostgreSQL lanes serialized.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| [Preflight](#doctor-and-smoke) | `python3.14 local-setup/stack.py doctor` | Required files, credential permissions, pinned images, Docker, Compose rendering, checkout ownership and free ports | Implemented |
| [Transport smoke](#doctor-and-smoke) | `python3.14 local-setup/stack.py smoke` | Dependency readiness, operator authentication, M1 replay and conflict, named-agent dispatch, native text and fixture audio | Qualified ([0040](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)) |
| [Unit tests](#unit-tests) | Five `.venv/bin/python -m unittest discover` commands | Offline behavior with isolated temporary fixtures | Implemented |
| [Explicit PostgreSQL lane](#explicit-postgresql-lane) | `make postgres-check` | Actual transactions, runtime privilege refusals, staging and activation, interrupted recovery and scoped access | Qualified ([0009](../docs/work-items/0009-p1-phase-c-postgres-cutover.md)) |
| [Phase D demo](#phase-d-case-authority-demo) | `make phase-d-demo` | Case authority in owned synthetic schemas and two disposable runtime containers | Qualified ([0010](../docs/work-items/0010-p1-phase-d-authority-and-waits.md)) |
| [Phase E demo](#phase-e-confirmed-mutation-and-completion-demo) | `make phase-e-demo` | Confirmed mutation and completion across five fresh installed-runtime containers | Qualified ([0011](../docs/work-items/0011-p1-phase-e-effects-and-completion.md)) |
| [Phase F demo](#phase-f-leased-worker-demo) | `make phase-f-demo` | Persisted wait restart, explicit confirmation and completion, and progress after admission pressure | Qualified ([0012](../docs/work-items/0012-p1-phase-f-leases-and-deployment.md)) |
| [Phase G business browser gate](#phase-g-business-browser-gate) | `make phase-g-demo` | Actual browser, container and trace observations for the business profile | Qualified ([0013](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)) |
| [H1 manifest](#validate-the-frozen-manifest) | `make p1-benchmark-plan` | Validates the frozen manifest and prints its digest; starts no Docker workload | Implemented |
| [H1 workload](#run-the-workload) | `make p1-benchmark` | Installed-service inquiry measurement with independent reconciliation and owned cleanup | Qualified ([0014](../docs/work-items/0014-p1-phase-h-workload-baseline.md)) |
| [P2 intake](#p2-verified-postgresql-intake-check) | `make p2-postgres-check` | HMAC association, durable input, concurrency, drift and process recovery in fresh marked P2 schemas | Qualified ([0024](../docs/work-items/0024-p2-verified-durable-intake.md)) |
| [P2 examples](#p2-standalone-and-p3-local-http-examples) | `make p2-demo` | Two actual P2 public-example and process-replay cases | Qualified ([0027](../docs/work-items/0027-p2-standalone-and-p3-http.md)) |
| [P3 example](#p2-standalone-and-p3-local-http-examples) | `make p3-demo` | A provider-free scripted policy request through a real loopback server and typed client | Qualified ([0027](../docs/work-items/0027-p2-standalone-and-p3-http.md)) |
| [P2 dispatch](#dispatch-gateway-agent-and-completion-checks) | `make p2-dispatch-check` | v1-to-v2 owner migration, bounded claims and attempts, and acceptance recovery | Qualified ([0028](../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)) |
| [P3 coordinator](#dispatch-gateway-agent-and-completion-checks) | `make p3-coordinator-check` | Immutable coordinator acceptance, replay and cancel, and fresh-process reconciliation | Qualified ([0028](../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)) |
| [P2 gateway](#dispatch-gateway-agent-and-completion-checks) | `make p2-gateway-check` | Fresh-process recovery under the original receipt and operation identity | Qualified ([0029](../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)) |
| [P3 execution](#dispatch-gateway-agent-and-completion-checks) | `make p3-execution-check` | Specialist invocation only through newly issued P1 attempts | Qualified ([0029](../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)) |
| [P2 agent](#dispatch-gateway-agent-and-completion-checks) | `make p2-agent-check` | Worker termination, database-observed claim expiry and replay | Qualified ([0030](../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)) |
| [P3 completion](#dispatch-gateway-agent-and-completion-checks) | `make p3-completion-check` | Strict issued results, receiver acceptance and one exactly confirmed fake supplier effect | Qualified ([0030](../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)) |
| [P2 revision routing](#revision-routing-and-registered-p3-lab-runners) | `make p2-routing-check` | The selected 22-case dual-authority gate | Qualified ([0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)) |
| [P3 contract checks](#revision-routing-and-registered-p3-lab-runners) | `make p3-contract-check` | Contract acceptance checks for P3-03 and P3-11 | Qualified ([0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)) |
| [P3-01 lab runner](#revision-routing-and-registered-p3-lab-runners) | `.venv/bin/python -m harness run P3-01` | 13 selected registered lab assertions | Qualified ([0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)) |
| [P3-03 lab runner](#revision-routing-and-registered-p3-lab-runners) | `.venv/bin/python -m harness run P3-03` | 8 selected registered lab assertions | Qualified ([0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)) |
| [P3-11 lab runner](#revision-routing-and-registered-p3-lab-runners) | `.venv/bin/python -m harness run P3-11` | 12 selected registered lab assertions | Qualified ([0031](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)) |
| [P2 send policy](#send-policy-and-protected-action-races) | `make p2-send-policy-check` | The selected synthetic P2 send-policy backend gate | Qualified ([0035](../docs/work-items/0035-send-policy-and-action-races.md)) |
| [P3 action races](#send-policy-and-protected-action-races) | `make p3-action-races-check` | 31 modes and 16 cases with two prewarmed SQL waiter graphs and three owned kills | Qualified ([0035](../docs/work-items/0035-send-policy-and-action-races.md)) |
| [P2 native build](#native-input-and-deadline-checks) | `make p2-native-build` | Builds the P2 SDK and the isolated p2-native.html entry; starts no service | Implemented |
| [P2 native check](#native-input-and-deadline-checks) | `make p2-native-check` | Host SDK, browser and gateway exercise against local Docker LiveKit and PostgreSQL | Qualified ([0036](../docs/work-items/0036-native-input-and-deadline-cancellation.md)) |
| [P3 deadlines](#native-input-and-deadline-checks) | `make p3-deadlines-check` | The selected P3 temporal gate | Qualified ([0036](../docs/work-items/0036-native-input-and-deadline-cancellation.md)) |
| [P2 communication](#playback-and-process-recovery) | `make p2-communication-check` | Explicit v6-to-v7 upgrade, interrupted migration, original identity, capacity, expiry and populated restore | Qualified ([0037](../docs/work-items/0037-playback-evidence-and-process-recovery.md)) |
| [P2 playback](#playback-and-process-recovery) | `make p2-playback-check` | Actual scripted SDK and browser audio for normal output, midpoint interruption and disconnect | Qualified ([0037](../docs/work-items/0037-playback-evidence-and-process-recovery.md)) |
| [P3 recovery](#playback-and-process-recovery) | `make p3-recovery-check` | Original-identity lookup after specialist or coordinator process loss | Qualified ([0037](../docs/work-items/0037-playback-evidence-and-process-recovery.md)) |
| [P2 rehydration storage](#current-case-rehydration-and-standalone-packages) | `make p2-rehydration-check` | The 18-group storage gate | Qualified ([0038](../docs/work-items/0038-case-rehydration-and-standalone-release.md)) |
| [P2 rehydration media](#current-case-rehydration-and-standalone-packages) | `make p2-rehydration-media-check` | The three-group scripted media gate across dormant rooms A and B | Qualified ([0038](../docs/work-items/0038-case-rehydration-and-standalone-release.md)) |
| [P3 package](#current-case-rehydration-and-standalone-packages) | `make p3-package-check` | Eight offline package assertions | Qualified ([0038](../docs/work-items/0038-case-rehydration-and-standalone-release.md)) |
| [P3 package lab](#current-case-rehydration-and-standalone-packages) | `make p3-package-lab-check` | The same eight plus eight actual standalone assertions | Qualified ([0038](../docs/work-items/0038-case-rehydration-and-standalone-release.md)) |
| [P2 workload plan](#bounded-workloads-and-standalone-image-gates) | `make p2-workload-plan` | Prints the plan; starts no workload | Implemented |
| [P3 document plan](#bounded-workloads-and-standalone-image-gates) | `make p3-document-plan` | Prints the plan; starts no workload | Implemented |
| [P2 workload](#bounded-workloads-and-standalone-image-gates) | `make p2-workload-check` | Bounded workload and dormancy study in fresh owned v7 profiles | Qualified ([0039](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)) |
| [P3 document source](#bounded-workloads-and-standalone-image-gates) | `make p3-document-check` | Twenty declared image cases over owned loopback HTTP | Qualified ([0039](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)) |
| [P3 document installed](#bounded-workloads-and-standalone-image-gates) | `make p3-document-package-check` | The same twenty cases from fresh installed artifacts outside the checkout | Qualified ([0039](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)) |
| [P2 operations plan](#operations-and-fixed-policy-profiles) | `make p2-operations-plan` | Prints the gate plan without running it | Implemented |
| [P2 operations build](#operations-and-fixed-policy-profiles) | `make p2-operations-build` | Builds the optional operations page through its own Vite entry | Implemented |
| [P2 operations](#operations-and-fixed-policy-profiles) | `make p2-operations-check` | The optional operations page with its loopback read server, PostgreSQL and browser lane | Qualified ([0040](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)) |
| [P3 fixed-policy plan](#operations-and-fixed-policy-profiles) | `make p3-fixed-policy-plan` | Prints the gate plan without running it | Implemented |
| [P3 fixed policy](#operations-and-fixed-policy-profiles) | `make p3-fixed-policy-check` | The standalone version 2 fixed-policy API through private source consumers | Qualified ([0040](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)) |
| [P3 fixed-policy package](#operations-and-fixed-policy-profiles) | `make p3-fixed-policy-package-check` | The same API through installed consumers | Qualified ([0040](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)) |
| [Result receiver plan](#result-receiver-qualification) | `make p2-result-receiver-plan` | Prints the finite sixteen-storage and four-return schedule | Implemented |
| [Result receiver](#result-receiver-qualification) | `make p2-result-receiver-check` | Isolated owner and runtime profiles, one scheduled receiver-caller kill and actual backup and restore | Qualified ([0043](../docs/work-items/0043-stable-result-delivery-and-return-context.md)) |
| [Result receiver package](#result-receiver-qualification) | `make p2-result-receiver-package-plan`, `make p2-result-receiver-package-check` | The offline archive and installed lane; zero actual storage or return assertions | Qualified ([0043](../docs/work-items/0043-stable-result-delivery-and-return-context.md)) |
| [Origin plan](#original-channel-input-qualification) | `make channel-origin-plan` | Prints the gate plan without running it | Implemented |
| [Origin unit tests](#original-channel-input-qualification) | `make channel-origin-unit` | Channel-origin unit tests | Qualified ([0044](../docs/work-items/0044-origin-bound-channel-policy.md)) |
| [Origin source gate](#original-channel-input-qualification) | `make channel-origin-check` | Fourteen actual assertions across sixteen owned process groups | Qualified ([0044](../docs/work-items/0044-origin-bound-channel-policy.md)) |
| [Origin package](#original-channel-input-qualification) | `make channel-origin-package-check` | Built and installed public artifacts with explicit fake ports | Qualified ([0044](../docs/work-items/0044-origin-bound-channel-policy.md)) |

Status uses the implementation status vocabulary. Qualified means the command
belongs to a selected gate whose pass is recorded in the linked work item; a passing
selected gate does not complete a whole charter row. Implemented marks preflight,
plan and build commands and the general offline unit lane. The
[cooperative worker pause](#cooperative-worker-pause-in-isolated-gates) describes
how the real-media helper pauses an owned worker; its setup observations remain
distinct from business results and media qualification.

### Doctor and smoke

`doctor` validates required files, private credential permissions, pinned images,
Docker availability, Compose rendering, checkout ownership and free ports before a
fresh start. In a git checkout it also refuses a tracked `.env`, `.secrets.env` or
`.env.providers`. That check uses file names only and reads no contents.

`smoke` checks real dependency readiness, operator authentication, M1 replay and
conflict, named-agent dispatch, native text and fixture audio reception. It does
not certify the three products' V1 scopes or actual model behavior.

The diagnostic worker admits one active room within its local memory budget. End
browser sessions before smoke. The command creates its own room and does not
terminate another active session to obtain capacity.

### Unit tests

Unit tests use isolated temporary fixtures:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_local_setup.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_rtc_agent.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_authorization.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_source_transfer.py' -v
```

For host-side tests, install the frozen root environment described in the
[root README](../README.md). Lifecycle stdout is structured and secret-redacted.
Keep runtime reports under the ignored .local directory, and inspect service logs
when a readiness or smoke stage fails.

### Explicit PostgreSQL lane

Install the frozen root environment with the local and agent extras, then complete
init, start and prepare-postgres. Then run:

```sh
make postgres-check
```

- The checker reads private setup credentials as data and clears ambient
  PostgreSQL target selectors.
- It creates and removes only its own isolated schemas and synthetic source,
  backup and supplier fixtures.
- It exercises actual PostgreSQL transactions, runtime privilege refusals, staging
  and activation, interrupted recovery and scoped application access.
- It never starts or resets the stack, and it never cuts over the live M1 database.
- Missing setup or database, failures, timeouts and skipped cases remain
  non-passing.
- Its machine report is .local/validation/p1-phase-c/postgres-gate.json.

Ordinary unit discovery is an offline lane and cannot substitute for this gate.

### P1 phase demonstrations

Each demonstration owns isolated state. Each section states what the demonstration
creates, cleans and preserves.

#### Phase D case authority demo

For the standalone Phase D demonstration, rebuild using start, then run:

```sh
make phase-d-demo
```

It uses only owned synthetic schemas and two disposable runtime containers. The
[case and continuation guide](../docs/case-and-continuation.md) defines setup, exact
confirmation, deadline and cleanup behavior.

#### Phase E confirmed mutation and completion demo

After rebuilding with start and preparing the two database roles, run:

```sh
make phase-e-demo
```

The host creates and removes one UUID-owned PostgreSQL schema and a labelled
fixture volume. Five fresh installed-runtime containers cover these steps:

1. seed the same supplier for inquiry and apply;
2. stop after supplier commit;
3. reconcile and cancel;
4. stop after receiver commit;
5. verify replay plus diagnostic pruning.

- Runtime containers receive only the restricted runtime credential.
- The temporary root container only initializes ownership of this invocation's
  checked fixture volume. The application runs as the existing unprivileged user
  with resource limits.
- The resulting .local/validation/p1-phase-e/container-demo.json is written as
  passed only after owned cleanup.
- The demo preserves M1 state and needs no provider account.

The [effects guide](../docs/effects-and-completion.md) describes identities,
confirmation, uncertainty, cancellation and retained receipts.

#### Phase F leased worker demo

After rebuilding and preparing database roles, run the isolated installed-runtime
demonstration:

```sh
make phase-f-demo
```

It owns a separate schema and labelled fixture volume and uses the actual worker
profile. It restarts a persisted wait, drives explicit confirmation and
completion, and proves progress after admission pressure. Passing evidence is
written only after owned cleanup. See the
[lease and worker guide](../docs/leases-and-workers.md) for exact semantics.

### Phase G business browser gate

`make phase-g-demo` runs isolated actual browser, container and trace
qualification for the business profile.

- The host evidence runner requires the frozen Python and pnpm workspace plus a
  prepared Playwright-managed Chromium or an explicit supported executable override.
- It owns its test schemas, containers and volumes and the loopback ports 13001 and
  18081.
- Ordinary M1 data is not mounted by the demo.

#### Prepare host browser tools

The Phase G host runner also requires the frozen local and agent Python extras, a
supported host Node runtime and pnpm 12.18.0. The container selects Node 26.13.0.
The core Docker lifecycle does not require these host browser tools. Install the
frozen workspace before running browser evidence:

```sh
corepack pnpm install --frozen-lockfile
make browser-setup
corepack pnpm --filter @livekit-ecosystem/local-console build
```

- Rebuild these host assets after console source changes. Before the browser
  opens, the helper verifies that the served index and compiled assets match this
  host distribution. The Docker image build does not create the host distribution.
- `make browser-setup` explicitly installs the Chromium build selected by the
  locked Playwright 1.65.0 dependency. Both browser lanes use that managed browser
  by default, and starting a gate does not download a browser.
- A separately installed Chrome version on the machine cannot silently select the
  default runtime.
- On a Linux host that also needs browser system libraries, run
  `corepack pnpm --filter @livekit-ecosystem/local-console exec playwright install --with-deps chromium`
  instead. A separate Linux host is not a prerequisite for this local POC.

After the preparation commands above, `make phase-g-demo` uses the prepared
managed browser directly.

#### Use an explicit browser executable

An explicit existing executable remains available for a declared comparison.
Resolve the pinned package's executable and pass it using structured arguments, so
paths with spaces remain one value:

```sh
.venv/bin/python - <<'PYTHON'
import subprocess
import sys
from pathlib import Path

resolver = (
    "import { chromium } from './apps/local-console/node_modules/@playwright/test/index.mjs'; "
    "process.stdout.write(chromium.executablePath());"
)
result = subprocess.run(
    ["node", "--input-type=module", "-e", resolver],
    check=True, capture_output=True, text=True, timeout=10,
)
browser = Path(result.stdout.strip())
if not browser.is_absolute() or not browser.is_file():
    raise RuntimeError("The explicitly installed browser is unavailable")
subprocess.run(
    [sys.executable, "local-setup/scripts/phase_g_demo.py", "--browser-executable", str(browser)],
    check=True, timeout=420,
)
PYTHON
```

The helper creates its own synthetic credentials and isolated runtime state from
the prepared local stack. Do not provide a real provider account or source private
configuration as shell code.

#### What the gate establishes

This gate establishes its declared browser, SDK, persistence and trace
observations.

- The first-class scripted input uses WebAudio and the bundled spoken fixture
  without overriding microphone APIs.
- The positive local source is bundled 16 kHz mono pulse-code modulation (PCM)
  audio through an owned WebAudio track and actual native SDK and WebRTC. It has
  bounded creation, publication and close, and late cleanup. Unresolved resource
  ownership blocks another media context.
- Input and status controls require the selected native agent's actual
  RoomIO-ready attribute plus active SDK state, rather than participant presence or
  a delay.
- Explicit End retires the media context. The next Join rehydrates the same durable
  task in a fresh room, while unknown initial acknowledgements reuse their frozen
  invocation.
- Token and task selection is memory-only. A hard reload requires explicit
  authenticated task resume.
- Real physical microphone permission denial is a separate negative test.
- Trace, video and HTTP Archive (HAR) recording is disabled. Screenshots require
  empty password inputs, and retained observations use allowlisted bounded fields.

The gate does not establish positive device capture, human hearing, general
automatic speech recognition (ASR), model or TTS quality, or the complete V1
charter. See the [Phase G work item](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
for inspected local results and remaining acceptance scope.

#### Optional hosted automation

The local-stack workflow declares Phase G after the PostgreSQL, Phase E and Phase F
gates. It uses the frozen workspace, a host console build and explicit bundled
Chromium, and it retains the existing failure diagnostics and preserve-state stop.
The 20-minute job budget has an estimated 12–15-minute normal workload, including
the added host and browser setup. This is a planning estimate, not an observed
hosted-run duration.

Existing workflow definitions are optional automation references. Remote
continuous integration (CI) and publication are outside the local POC scope and do
not block P1 completion or P2 work. The action and browser setup follow the
official [setup-node release](https://github.com/actions/setup-node/releases/tag/v7.1.0)
and [Playwright CI guide](https://playwright.dev/docs/ci).

### Declared inquiry workloads

The Phase H1 S-I06/P1-I27 controller is an explicit opt-in tool for measuring the
inquiry workload. It is separate from normal startup, smoke and the acceptance
catalog. The [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md)
records the completed local inquiry measurement and its limits.

#### Validate the frozen manifest

Freeze the reviewed [versioned manifest](../harness/workloads/p1-inquiry-v1.json)
before measuring:

```sh
make p1-benchmark-plan
```

This validates the default manifest and prints its canonical digest, six
experiment names and the status not_started. It starts no Docker workload and is
not measurement evidence. The equivalent command-line interface is
.venv/bin/python local-setup/scripts/p1_benchmark.py, and --manifest selects an
explicitly reviewed bounded local manifest. Changing a schedule or budget requires
a new reviewed declaration, not relabelled results.

#### Run the workload

Actual execution requires:

- the frozen local environment;
- the owned foundation network and PostgreSQL service;
- prepared restricted migration and runtime roles, from the existing init, start
  and prepare-postgres procedure;
- a freshly built shared Python image matching the inspected source.

The runner creates and upgrades its own empty UUID-owned schema. It never selects
the application schema or M1 data. After setup and manifest review, execution is
explicit:

```sh
make p1-benchmark
```

This invokes .venv/bin/python local-setup/scripts/p1_benchmark.py --run.

- It starts installed API and worker containers without checkout mounts.
- It verifies installed-source provenance and configured cgroup limits.
- It owns separate supplier/receiver and API volumes.
- It reads existing stack credentials privately. They are not sourced as shell
  code or copied into retained evidence.
- It cleans only the owned schema and fixtures.

Missing setup, useful progress, independent receipts or owned cleanup is
non-passing. The isolated inquiry environment does not enable native media or OTLP
trace export. Its HTTP and worker observations are separate from the Phase G trace
and media lane.

#### Frozen declaration

These values are declarations fixed before an actual run, not observations.

| Frozen declaration | Meaning before an actual run |
| --- | --- |
| Six modes | steady-w1 and steady-w2: 20 offers at one-second spacing. burst-w1 and burst-w2: 32 offers. saturation-w1 and saturation-w2: 32 staged offers with workers initially stopped. |
| Expected new-work totals | 168 offers, 120 admissions and 48 capacity rejections. Replay, GET and cancel calls are separate. |
| HTTP pressure | One shared concurrency slot in steady modes and four in burst and saturation modes. Submit, replay, GET and cancellation use the same semaphore and pool. |
| Saturation | Admit eight, prove original-key read and replay at capacity, reject 24 new identities, then start workers with an active cap of one. |
| Resources | API and each worker: 1000 millicores, 512 MiB and a pids limit of 128. These configured caps are not measured requirements or production capacity. |
| Time and evidence bounds | 180 seconds per experiment within a 600-second run, a bounded 90-second owned cleanup and at most 4096 raw records. Each request network timeout is at most five seconds within the remaining budgets. |

#### Observation semantics

Case observation performs one global round-robin GET, then sleeps 250 ms. HTTP and
shared-slot waiting add delay, so this is neither a 250 ms per-task refresh nor a
hard tick.

The runner records four moments separately: the scheduled offer, the first HTTP
start, a known validated acknowledgement and the first validated successful
inquiry snapshot. A successful submit or replay projection can be the first result
observation. Unknown HTTP attempts record their finish time without claiming an
acknowledgement. Reported result latency includes caller queueing and observer
lag. It is not an exact supplier completion instant.

#### Resource probe semantics

- Resources come from sequential docker-exec Python cgroup-v2 probes at a
  one-second target cadence.
- Evidence retains actual probe start, end and duration, and skipped intervals. A
  missed slot is not caught up with back-to-back probes.
- The observer's in-container CPU, memory and process identifier (PID) overhead is
  included.
- memory.current is accounted cgroup memory, not resident set size (RSS) or a peak.
  pids.current counts kernel tasks and threads.
- CPU records use cumulative microseconds with the observed first, last, delta and
  window values.
- The resource window includes post-inquiry replay, cancellation and delivery
  checks.
- Host, Docker virtual machine (VM), shared PostgreSQL and outside-cgroup overhead
  are excluded.

See [measurement semantics](../docs/observability.md) for cap-versus-usage and
clock rules.

#### Reports and pass criteria

Reports under the ignored `.local/validation/p1-phase-h/<run-id>` directory retain
the frozen workload, bounded safe raw records and source, image and machine
provenance. A `<experiment>.measurement.json` snapshot precedes cleanup. Its
measured status is not a passing phase.

A per-experiment or aggregate pass requires independent inquiry reconciliation,
unchanged booking with zero supplier mutations, and verified owned cleanup.
Preserve failed records, the separately recorded cancellation, outcome and
delivery, and closed Phase G artifacts.

Before temporary capture files are removed, each original failure retains a
fixed-enum code and operation, plus any observed exit code, timeout flag, command
budget and elapsed time. Cleanup failures are recorded separately. Raw argv,
stdout, stderr, environment values, bodies and exception text are not retained in
public failure diagnostics.

#### Environment metadata and scope

The controller automatically reports the host system, architecture and Python
version, and the installed runtime architecture and versions. Docker VM CPU and
memory and shared-host context require separate operator collection. A supporting
environment.json is not automatic runner output. Summaries use only the sample
count, minimum, median and maximum.

This inquiry slice does not measure media, model quality, physical microphone
capture or production scale. H1 retains its historical inquiry scope. The current
H2, host/Linux artifacts and the selected provider_real v2 local P1 release are
separately qualified in the
[release handoff](../docs/work-items/0019-p1-phase-h-release-qualification.md).
local_real and physical quality remain unqualified, and complete P2/P3 acceptance
remains pending.

### Cooperative worker pause in isolated gates

The real-media helper pauses and resumes an owned worker cooperatively. These
setup observations remain distinct from business results and media
qualification.

#### Pause

1. After installed-source validation, the helper sends SIGUSR1 only to its exact
   UUID-owned running worker. A request flag is not an acknowledgement.
2. WorkerRuntime reaches its quiescent outer-loop checkpoint only after the child
   is reaped, its lease is released and post-step queue SQL has finished.
3. The helper then uses the installed WorkerHealth.is_quiescent(maximum_age_seconds=10)
   check, requires a separate active=0 durable snapshot, and applies the existing
   OS pause.

Arming, signalling, health acknowledgement, idle observation and pause share the
original 100-second setup deadline. An active=0 sample alone cannot prove that the
parent is out of SQL.

#### Resume

Recovery starts its original 45-second clock before the unpause, SIGUSR2 and a
fresh WorkerHealth.ready acknowledgement. Ready may already report one active
child. The clock therefore includes resume overhead rather than starting a new
window after the reply.

- The helper owns possibly lost signal and pause acknowledgements before issuing
  them. An unresolved resume or cleanup remains non-passing.
- Resume and close share the existing 12-second ceiling, without resetting a failed
  attempt's deadline.
- SIGTERM and SIGINT remain sticky shutdown requests. SIGUSR2 cannot reverse
  shutdown.
- No model, provider or browser control gains maintenance or mutation authority.

#### Retained proof

The retained proof has an exact nine-field worker_quiescence record: schema,
resumed phase, observed and resolved flags, one quiesce and one resume signal, and
positive health and idle observation counts bounded at 2,001. The independent real
acceptance consumer rejects absent, unknown, coerced, partial or repeated-signal
proof.

### P2 and P3 qualification gates

These opt-in gates exercise P2 and P3 slices against local infrastructure. The
[qualification gates guide](../docs/qualification-gates.md) summarizes them, and
each work item owns exact counts, failures and evidence.

- Run them from the repository root after frozen dependency setup. Gates that use
  PostgreSQL also need the local stack and the restricted database roles from init,
  start and prepare-postgres.
- A passing selected gate does not complete a whole charter row. Full P2/P3 charter
  registration remains planned.

#### P2 verified PostgreSQL intake check

After the ordinary local init, start and prepare-postgres steps and the frozen
Python, Node and pnpm setup, run:

```sh
make p2-postgres-check
```

- This explicit lane uses the existing settings loader privately, fixed loopback
  and database roles, and fresh marked P2 schemas.
- It compiles source with pinned TypeScript, then tests actual hash-based message
  authentication code (HMAC) association, durable input, concurrency, drift and
  process recovery.
- It needs no P1 or P3 service, carrier account, provider key or hosted resource.
- It never resets a volume or replaces the existing application schema.

For retained evidence, use local-setup/scripts/p2_postgres_check.py --report with
a fresh filename under .local/validation/p2-postgres. Existing reports are not
overwritten. Raw child capture is bounded and private and is removed after
inspection. Cleanup failure, missing setup, zero tests or skips cannot pass.

This is disposable intake qualification, not a started P2 gateway or a persistent
user workspace. The local runtime role is shared with P1, so this test does not
establish separate database-principal isolation. Do not expose a P2 service before
that separation and the later authenticated HTTP and runtime gates are qualified.

#### P2 standalone and P3 local HTTP examples

```sh
make p2-demo
make p3-demo
```

`make p2-demo` runs only the two actual P2 public-example and process-replay
cases, after frozen bootstrap.

- It requires the same explicit local PostgreSQL preparation as the
  [intake check](#p2-verified-postgresql-intake-check). The wrapper's --example
  option selects those cases without changing ordinary setup.
- The demo owns disposable schemas and runtime-only child credentials and closes
  them before it returns a safe report.
- The preview explicitly reports pending input and not_executed business work.

`make p3-demo` sends a provider-free scripted policy request through a real
loopback server and typed client.

- It builds the specialist package, creates an ephemeral listener and a synthetic
  bearer and evidence, prints the bounded candidate observation and closes its
  client and server.
- It needs the pinned Node and pnpm environment, not PostgreSQL, P1 or P2 services
  or provider keys.

Neither command starts a persistent product service, modifies the existing
application case or qualifies UI or media.

#### Dispatch, gateway, agent and completion checks

After the same frozen local PostgreSQL and Node setup, run:

```sh
make p2-dispatch-check
make p3-coordinator-check
make p2-gateway-check
make p3-execution-check
make p2-agent-check
make p3-completion-check
```

The dispatch and coordinator selectors come from
[0028](../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md), and the gateway
and execution selectors from
[0029](../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md). The
[agent recovery and completion phase](../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
adds an independently owned scripted-agent worker and explicit first-result
delivery and action paths. What each selector verifies:

- **P2 dispatch** (`make p2-dispatch-check`) tests v1-to-v2 owner migration,
  preserved identities, bounded claims and attempts, current association and
  independent-operation acceptance recovery. It never implicitly upgrades an
  application schema.
- **P3 coordinator** (`make p3-coordinator-check`) explicitly creates an owned
  p1_work_ profile through public P1 administration. It verifies immutable
  coordinator acceptance, replay and cancel, and fresh-process reconciliation. It
  separately invokes the local TypeScript specialist through Python sockets.
- **P2 gateway** (`make p2-gateway-check`) starts actual loopback gateway processes,
  acknowledges signed input and terminates one before dispatch. It verifies
  fresh-process recovery under the original receipt and operation identity.
- **P3 execution** (`make p3-execution-check`) explicitly seeds v1 acceptance,
  upgrades its owned P1 profile to v2 and invokes the scripted specialist only
  through newly issued P1 attempts. It verifies historical cancellation and stale
  results, current useful read-only output, and a postcommit forced exit with a
  fresh read.
- **P2 agent** (`make p2-agent-check`) proves worker termination, database-observed
  claim expiry and replay while the gateway stays alive.
- **P3 completion** (`make p3-completion-check`) explicitly prepares disposable work
  v3 and case v4 profiles. It then verifies strict issued results, receiver
  acceptance and reconciliation, and one exactly confirmed fake supplier effect.

Reports go to fresh destinations: .local/validation/p2-postgres for the P2
selectors, and .local/validation/p3-coordinator, .local/validation/p3-execution
and .local/validation/p3-completion for the P3 selectors.

Rules for these gates:

- The gates use synthetic data, runtime-only child credentials and bounded owned
  processes. Marked schemas and fixtures are removed.
- Runtime children receive only runtime credentials. Explicit owner preparation,
  reconciliation and cleanup receive only owner credentials.
- Missing setup, skips, timeout, private child output or incomplete cleanup cannot
  pass.

These are disposable local qualification lanes, not persistent deployed gateways
or coordinator workers. No normal startup, reset or profile selection changes. The
ordinary Compose profile and console still serve their documented foundation and
business paths, and these gates do not deploy P2 or P3 into that default UI.

What the results do and do not prove:

- P3 case preflight is explicitly synthetic in the coordinator gate, and its
  independent transport calls are not P1-issued attempts.
- A cancellation receipt requests cancellation. It does not prove stopped
  computation.
- A candidate read is not permission. P1 work v3 checks current work eligibility
  and exact case confirmation atomically, then the existing leased worker performs
  the fake effect outside SQL.
- The receiver accepts immutable bytes under a stable identity. It proves neither
  playback nor human acknowledgement.
- Existing possible deliveries use lookup only.
- Full current-case, action, delivery and media integration, and all complete
  product, media and broader recovery gates, remain later and separate gates.

#### Revision routing and registered P3 lab runners

P2-I10's explicit RevisionRouter decodes a strict investigation command from
already accepted, authenticated inbox input. Choose one case authority:

- the owner-installed standalone reference PostgreSQL case authority; or
- public P1 compare-and-set (CAS) through the loopback bridge.

Never run both as authorities for the integrated case. Existing P1 v4 is
unchanged.

- A lost revision acknowledgement (ACK) remains unknown. There is no command
  receipt and no automatic retry or rebase.
- Retained inbox reads authorize account history, not the current sender
  association.
- The separate linked-confirmation router now rechecks the original current
  association before a new call. Atomic cross-store revocation remains unqualified.

The selected 22-case dual-authority gate has passed. With the existing local
restricted-role PostgreSQL setup and pinned host Node, run:

```sh
make p2-routing-check
make p3-contract-check
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

P3's selected registered lab assertions are 13, 8 and 12 for P3-01, P3-03 and
P3-11. Required setup, exact inventory, report freshness and owned process, schema
and socket cleanup are mandatory. Default Compose and console still serve the
existing foundation and business paths. These gates add no paid provider call,
native audio, real carrier, image decoding or full release.

#### Linked consent and result projections

The [phase handoff](../docs/work-items/0032-linked-confirmation-and-result-projections.md)
implements a separate opt-in bridge confirmation capability and explicit host
projection tooling. Selected local qualification passed. This slice has no
separate command in this guide.

- A trusted controller prepares exact P1 quotes. Immutable P2 prompts preserve the
  original canonical bytes and the UUID5 proposal identity.
- Only explicitly linked user consent and the fixed configured mapping reach the
  public commit_confirmation call.
- Its original command receipt can reconcile a lost ACK through explicit replay.
  Revision CAS remains a different capability without that receipt.
- No quote or confirmation tool is exposed to the model, and the bridge does not
  atomically fence P2 revocation.

Work-profile v4 is an explicit owner-only v3 upgrade, separate from booking v4. It
adds a stable source UUID, scoped result events and cursors, and runtime performs
no DDL. P3 separately initializes bounded metadata and checkpoints and reads
original results through public ports. Stored applicability is immutable as-of
evidence, not refreshed current truth, delivery permission or action permission.
Serving defaults, provider keys, named volumes and ordinary Compose and console
composition stay unchanged.

#### Outbound replies and completion processing

The [completed phase](../docs/work-items/0033-outbound-replies-and-completion-processing.md)
adds locally qualified explicit host tooling. Its 24-case P2 and 16-case P3 gates
and isolated installed consumers passed without adding a default daemon.

P2 owner-upgrades its inbox profile to v3 for immutable-recipient replies and
versioned route and suppression checks.

- Carrier I/O remains outside SQL, after a guarded possible-send reservation.
- An attempt with no known result remains unknown, not an automatic retry. Later
  route changes cannot retarget the original attempt.
- Ordinary carrier acceptance is distinct from delivery and human acknowledgement.

P3 owner-upgrades its projection profile to v2 without changing P1 work v4.

- Its bounded explicit processor retains a scan cursor and a separate contiguous
  terminal ACK watermark.
- An unknown event remains unacknowledged while a later eligible result can
  progress.
- Exact known original receipts survive restart and cancellation. Processing has no
  source ACK, action or consent authority.
- Existing possible-send absence stays lookup-only.

Default Compose and console, provider credentials and named volumes remain
unchanged. No automatic booking-completion handoff is added.

#### Callback evidence and applicability refresh

The [completed phase](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
completed selected local phase gates for P2-I13 and P3-I11.

- Callback APIs require explicit owner inbox v4 setup.
- P3 refresh and display metadata requires an explicit owner projection v3
  upgrade.
- P1 work v4 and booking v4 remain unchanged.
- No new default daemon, Compose or console route, provider credential or paid
  call is introduced.

Callbacks authenticate with a separate raw-byte HMAC capability. They correlate
exact old attempts independently of the current sender association, and their
evidence cannot open a resend. Refreshed applicability uses explicit per-result CAS
and separate as-of source, case and time observations. Hiding display preserves all
identities and unresolved processing.

| Bound | Default | Maximum |
| --- | --- | --- |
| Callbacks in total | 10000 | 100000 |
| Callbacks per attempt | eight | 32 |
| Refresh commands in total | 3000 | 30000 |
| Refresh commands per event | four | eight |

Callback bytes are capped at 4096, and refresh receipts are at most 4096 bytes.
The signature window is 60 seconds and is rechecked against database time after
admission. Equal replay remains available at capacity for the profile lifetime. No
physical deletion or capacity reclamation exists.

The isolated role-separated actual gates and offline installed consumers passed
their selected assertions. Existing quickstarts retain their qualified scope.

#### Send policy and protected-action races

The [completed send-policy and action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. With the documented
restricted-role setup, these commands passed their selected synthetic backend
gates:

```sh
make p2-send-policy-check
make p3-action-races-check
```

P2 rules:

- P2 policy APIs require explicit owner inbox v4-to-v5 maintenance and quiescence,
  and they preserve all old request, result and callback bytes.
- Ordinary possible sends remain held.
- A separately trusted cooperating provider may reuse the frozen original
  operation bytes and key only under a new explicit recovery-controller command and
  current permission.
- Retain callback exact-attempt correlation and vetoes. Never retarget the original
  address.

P3 rules:

- P3's new gate uses the unchanged public work v4 and booking v4 guards and
  independent supplier fixtures, with no projection upgrade or new daemon.
- Its 31 modes and 16 cases require two prewarmed SQL waiter graphs and three owned
  kills under a 180-second total budget: 165 seconds of work and 15 seconds of
  cleanup.

Existing callback and applicability commands retain the previous checkpoint's
passing scope. No provider key, default Compose or console change, named-volume
reset or automatic booking-completion handoff is added.

#### Native input and deadline checks

The [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
adds an isolated p2-native.html build and a host SDK, gateway and browser exercise
against local Docker LiveKit and PostgreSQL. It owns exact evidence and
prerequisites.

- Default M1/P1 UI, services and persistent state remain unchanged.
- Explicit owner v6 setup adds two native tables while preserving old channel
  identities.
- The scripted profile needs no provider keys.

Run these after frozen dependency setup and the documented local stack and
restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Build the isolated native page | `make p2-native-build` | Builds the P2 SDK, then the isolated p2-native.html entry to dist-native; starts no service and changes no default console entry |
| Run the native exercise | `make p2-native-check` | Owns the selected qualified host SDK, browser and gateway exercise against local Docker LiveKit and PostgreSQL |
| Run the P3 temporal gate | `make p3-deadlines-check` | The qualified selected P3 temporal gate |

Scripts use ordinary local setup and never provider credentials. Recorded outcomes:

- The selected six-group actual native and installed Python/npm artifact gates
  passed.
- The final selected phase checks and the affected media rerun after the UI hint
  update passed.
- P3's selected source and installed eighteen-case deadline gates and forty-six
  compatibility assertions passed without production runtime changes.

#### Playback and process recovery

The [completed playback and recovery handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md)
owns selected P2-I17/P3-I14 qualification. Use the ordinary local LiveKit and
PostgreSQL services and the pinned development tools. Provider keys are
unnecessary.

```sh
make p2-communication-check
make p2-playback-check
make p3-recovery-check
```

These commands create disposable, UUID-owned profiles.

- **P2 communication** explicitly upgrades v6 to v7. It verifies interrupted
  migration, original identity, scoped source evidence, capacity, fresh expiry,
  populated restore and retained I/O.
- **P2 playback** is a separate gate. It runs actual scripted SDK and browser audio
  for normal output, midpoint interruption and disconnect without a completion
  report. A compatible Chromium installation is required. The helper accepts an
  explicit --browser-executable when invoking
  local-setup/scripts/p2_playback_check.py directly.
- **P3 recovery** exercises explicit original-identity lookup after specialist or
  coordinator process loss, through existing public P1 authorities. It does not
  install another execution owner.

All helpers bound children, capture, deadlines and cleanup, and they retain safe
failure context. They do not change ordinary named volumes, default UI or Compose,
providers or business consent.

#### Current-case rehydration and standalone packages

The [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records the implemented P2-I18/P3-I15 interfaces and their passed selected
qualification. Default M1/P1 services, provider qualification, data and pinned
images stay unchanged. After frozen setup, local services and restricted-role
preparation, run:

```sh
make p2-rehydration-check
make p2-rehydration-media-check
make p3-package-check
make p3-package-lab-check
```

The P2 18-group storage gate checks:

- current native and SMS permission, separately from retained history;
- coherent bounded P2 sections;
- one allowlisted public P1 get;
- a final fresh permission admission.

Case and history observations are non-atomic. Source fingerprints and observed
times can change while the case revision remains the same. Reading or refreshing
creates no acceptance, command, send, generation or consent. Public P1 revision 0
is displayed honestly, and native input still requires its positive-revision
contract. No automatic 0-to-1 mapping or case revision is allowed.

The separate three-group scripted media gate requires the pinned managed Chromium
and the actual local selective forwarding unit (SFU, the LiveKit server) and
PostgreSQL. Its sequence is:

1. The application closes room A's real SDK and RTC owners.
2. The parent deletes A and proves that neither A nor B exists.
3. The fixed authenticated SMS runs in that dormant interval.
4. The parent then creates B.
5. Python waits for the exact owned B-ready marker and the known original SMS
   result before enabling a fresh mint.
6. B loads the current case and the original voice, text and SMS history before SDK
   readiness. Only a new accepted input generates B's reply.

Old response evidence grants no current playback, interruption, human
acknowledgement or mutation authority.

P3's default package command has eight offline assertions: a fresh P1 dependency
wheel; P3 wheel, sdist, rebuilt and specialist npm parity; isolated public imports
and types; and installed examples. The explicit lab command repeats those eight and
adds eight actual standalone assertions, for sixteen assertions in total. These are
not sixteen PostgreSQL scenarios.

- The lab command needs the existing restricted PostgreSQL roles and a sole local
  gate slot.
- It uses a local specialist and receiver, separately supplied exact synthetic
  consent, one leased fake effect, owned consumer loss and a fresh original replay.
- Owner and worker instrumentation remains test-only. There is no P2 gateway, SFU
  or provider requirement.

Recorded results of the selected synthetic local runs:

| Gate or check | Result |
| --- | --- |
| P2 18-group storage gate | Passed in 6.534 seconds |
| P2 three-group media gate | Passed in 35.797 seconds |
| P3 combined 16-case gate | Passed in 58.885 seconds |
| Isolated P2 Python consumption | 111 tests over nine payloads in 15 commands passed (52.364 seconds) |
| npm consumer | Seven stages passed in 2.1696 seconds |
| P2 compatibility | 166 assertions passed in 98.997 seconds |
| Closure checks | Passed: 2148 Python and 1224 TypeScript tests (503 console, 632 P2, 89 P3); broad/strict typing of 144/132 files; formatting of 387 files; 113 documentation checks; 29 Mermaid syntax checks |
| Ordinary doctor and smoke | Preserved ten audio frames and the original M1 state |

The storage, media and P3 runs had exact source and archive inventories and actual
owned cleanup. These results are observations, not latency or capacity guarantees.

- Full P2/P3 charter registration remains planned. These selected gates do not
  complete all seventeen P2 or fourteen P3 acceptance rows.
- Retain unresolved child, bridge and read owners and private work for explicit
  cleanup. Reaping children precedes schema deletion, and bridge settlement
  precedes reader closure.
- Failed attempts remain failed.
- These commands perform no remote CI or provider inference.

#### Bounded workloads and standalone image gates

The [completed handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records passing selected P2-I19/P3-I16 qualification. Use the frozen Python
3.14.10 and Node 24.22.2 host toolchain and existing caches:

```sh
make p2-workload-plan
make p3-document-plan
make p2-workload-check
make p3-document-check
make p3-document-package-check
```

Plans start no workload.

The P2 workload check uses ordinary restricted-role local PostgreSQL settings and
fresh owned v7 profiles:

| Setting | Value |
| --- | --- |
| Retained limits | 64/1,024 |
| Seed | 39 |
| Dormant samples | 0, 64, 256 and 1,000 |
| Public setup and read windows | At most 64 |
| Selected two-gateway phase | At most eight runtime SQL connections and sixteen retained runtime SQL operations, plus two simultaneous owner control connections (ten combined) |
| Time budget | 360 seconds total, including twenty cleanup seconds |

It changes no schema version or default service and allocates no agent or room per
dormant case. Selected workload qualification passed. Resource samples describe
the configured local profiles and do not establish production capacity. Never
reset existing data to run this study.

The P3 document image gates have these bounds:

| Setting | Value |
| --- | --- |
| Source mode | Owned loopback HTTP and fixed worker threads, without PostgreSQL, rooms, provider settings or models |
| Installed mode | Builds fresh current Python and npm artifacts through the maintained offline package builder, then runs the same twenty declared image cases outside the checkout |
| Time bounds | 120 seconds (source) and 360 seconds (installed), including twenty cleanup seconds |
| Process children | A shared ceiling of thirty-two |
| PNG input | Actual PNG bytes are bounded to 2 MiB and 2048×2048 and checked before the scripted provider |
| Supported PNG subset | Noninterlaced RGB8 and RGBA8, intentionally narrower than full PNG |

Sources and the independent literal oracle are copied as explicit consumer setup.
Public examples load none of them implicitly.

- Reap actual owned children and process groups before deleting their private work.
- Worker and provider settlement and public close retry are separate from cancel
  ACKs.
- Preserve failed attempts and bounded finite diagnostics.
- These gates perform no optical character recognition (OCR), paid inference, P1
  durable image work or action, or default-stack deployment. Missing setup is
  non-passing.

#### Operations and fixed-policy profiles

Use the [operations and policy handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
and the [P2 operations guide](../projects/channel-continuity/OPERATIONS.md). The
default Compose topology and console remain unchanged.

```sh
make p2-operations-plan
make p2-operations-build
make p2-operations-check
make p3-fixed-policy-plan
make p3-fixed-policy-check
make p3-fixed-policy-package-check
```

P2 operations page:

- The page uses its own Vite build entry and an explicitly configured loopback read
  server. PostgreSQL remains the existing local restricted-role service.
- No second database, queue, image, public carrier or provider credentials are
  required.
- The P2 gate accepts --browser-executable through its Python helper for a
  prepared Chromium installation.
- Serialize its PostgreSQL lane with the existing durable and media gates.
- The page uses a scoped operator token and a persistent private cursor key
  configured by its host. The browser receives no mutation credential.
- Set only the documented variables in the project guide.
- The app's declared P2 workspace dependency is installed with the frozen lock. Its
  optional build compiles the public P2 package first.
- Default console compilation excludes that optional graph, preserving the existing
  standalone console Docker build boundary.

P3 fixed policy:

- The gates require the pinned local Python and Node tools and installed build
  dependencies, but no PostgreSQL, SFU, external models or .env.providers.
- They create finite loopback services and private source and installed consumers.
- Version 2 is explicitly selected and standalone. Version 1 defaults and the
  durable P3 runner remain unchanged.
- No image or policy content grants tools or confirmation.
- Failed normal attempts remain non-passing and retain safe evidence. Remove owned
  state only after actual dependent processes and readers settle.

Selected 0040 qualification passed for the optional operations profile and the
standalone fixed-policy API. The completed handoff records the exact source,
installed, media-compatibility and cleanup scope. Existing default doctor and smoke
passed eight checks and ten diagnostic audio frames with the original M1
preserved. Selected P2-I21/P3-I18A qualification subsequently passed in 0041, and
selected P3-I18B native RTC text qualification passed in 0042. Later selected
joined voice/text/SMS and provider journeys and the demo video are recorded in
[0046](../docs/work-items/0046-joined-showcase-providers-and-demo.md); full joined
release qualification remains separate. A build or healthy service alone cannot
qualify it.

#### Result receiver qualification

```sh
make p2-result-receiver-plan
make p2-result-receiver-check
make p2-result-receiver-package-plan
make p2-result-receiver-package-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Print the schedule | `make p2-result-receiver-plan` | Prints the finite sixteen-storage and four-return schedule |
| Run the receiver gate | `make p2-result-receiver-check` | Uses isolated owner and runtime PostgreSQL profiles, one scheduled receiver-caller kill and actual backup and restore; creates no room, provider call or carrier send |
| Run the package lane | `make p2-result-receiver-package-plan` and `make p2-result-receiver-package-check` | Run the separate offline archive and installed lane: twenty-five owned groups, eight existing package assertions and twenty copied fake-port tests |

The package lane claims zero actual storage or return assertions. The
[work item](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
records prerequisites, exact outcomes, retained failures and full-phase status.

#### Original channel-input qualification

With the existing local PostgreSQL and API and the pinned host Python and Node
toolchain, run:

```sh
make channel-origin-plan
make channel-origin-unit
make channel-origin-check
```

The selected source gate passed fourteen actual assertions across sixteen owned
process groups, with complete cleanup.

- It joins native and signed simulated-SMS input to original P1 work, issued policy
  results and the current P2 receipt and read.
- It uses three disposable schemas and one owned post-commit ACK-host kill. The
  normal application and M1 record remain unchanged.
- Reports use fresh timestamped paths under .local/validation/p2-channel-origin.
  Failed runs remain retained.

The separate package check validates built and installed public artifacts with
explicit fake ports. It does not repeat the actual database schedule:

```sh
make channel-origin-package-check
```

See the [origin work item](../docs/work-items/0044-origin-bound-channel-policy.md)
for exact scope, failures and evidence. Integrated browser voice, text and SMS,
provider composition, restart discovery and the final demo video remain separately
gated.

## Troubleshooting

When a lifecycle operation is interrupted or fails, inspect the current state and
retry only the authorized bounded operation. Do not reset or regenerate
credentials to hide a failed recovery.

| Symptom | Cause | Fix |
| --- | --- | --- |
| The default ports are already in use | Another stack already uses the defaults | Set `STACK_PROJECT` and the port variables, then run init before start ([Isolated stack per checkout](#isolated-stack-per-checkout)); `doctor` checks free ports before a fresh start |
| The manager refuses to mutate a container or volume | It acts only on resources labelled for this checkout and project, with matching credential-derived volume labels | Retain private credentials with their volumes; regenerating them does not adopt existing data |
| Smoke cannot obtain a room | The diagnostic worker admits one active room, and smoke does not terminate another session | End browser sessions before smoke |
| A readiness or smoke stage fails | An unhealthy dependency keeps startup or smoke unsuccessful | Inspect service logs; select one service with `--service`, for example `logs --service rtc-agent`, when the combined tail obscures its events |
| prepare-postgres reports a credential or policy mismatch | An existing credential or policy does not match, and prepare-postgres refuses without rotating a password | Changing credentials on an initialized volume requires a separate explicit role and password operation |
| prepare-business fails with a fixed stage and code | The reported stage failed; private recovery artifacts are retained | Keep the bootstrap folder, source, backups and credentials; do not replace the source or change the endpoint or schema; reset is not a recovery step |
| prepare-business refuses existing staging state | The staging state is conflicting, nonempty or unowned | Inspect and retain it rather than deleting it to force startup |
| A worker cannot start on a fresh migrate-postgres target | That target is STAGING | Use the [business preparation](#first-persistent-p1-business-workspace) for a persistent workspace |
| upgrade-coordination refuses to run | Unmanaged running legacy inquiries exist | Reconcile them on v3 first |
| The Phase G helper finds that host assets do not match | Console source changed after the host distribution was built; the Docker image build does not create it | Rebuild the host console distribution ([Prepare host browser tools](#prepare-host-browser-tools)) |
| The managed Chromium is not installed | Starting a gate does not download a browser | Run `make browser-setup` |
| Joined setup rejects the target directory | An existing target directory is rejected | Prepare a new directory; a profile holds sixteen inputs |
| The joined launcher finds an existing active marker | Unresolved cleanup or a crash left the original active marker in place | The original live launcher reobserves its cleanup automatically; a fresh launcher fails closed and offers no automatic crash recovery or destructive repair |
| A gate reports missing setup, skips or a timeout | The documented setup is incomplete; the result is non-passing | Complete the documented setup and rerun |

## Reference

### Services

| Component | Compose service | Profile | Responsibility |
| --- | --- | --- | --- |
| LiveKit server | `livekit` | Default | Self-hosted media server |
| PostgreSQL | `postgres` | Default | Database roles and the versioned P1 schema |
| Control API | `control-api` | Default | Authenticated M1 intake; business mode under start-business |
| Diagnostic worker | `rtc-agent` | Default | Deterministic Agents SDK worker that echoes text and counts audio frames |
| Browser console | `console` | Default | Its nginx proxy resolves `control-api` per request |
| Jaeger tracing UI | `jaeger` | Optional observability profile; also started by start-business | In-memory storage |
| One-shot migration | `p1-migrate` | Optional migrations profile | Run by migrate-postgres with only the migration credential |
| Leased P1 pull worker | `p1-worker` | p1-workers profile; also started by start-business | Uses the worker_data volume |
| Native conversation agent | `conversation-agent` | p1-business profile | Native scripted conversation agent |
| Local model engines | `p1-llm`, `p1-stt` and `p1-tts` | p1-models profile (local real inference) | Internal network, no host ports and read-only model mounts |

### Profiles

| Profile | Services | Started by | Notes |
| --- | --- | --- | --- |
| Default | `livekit`, `postgres`, `control-api`, `rtc-agent` and `console` | `start` | Serves M1 and the transport diagnostics with business mode off |
| `observability` | `jaeger` | `start --observability`; also `start-business` | UI readiness alone does not establish export coverage |
| `migrations` | `p1-migrate` | `migrate-postgres`, once | Prepares a staging schema with only the migration credential |
| `p1-workers` | `p1-worker` | `start-workers`; also `start-business` | Requires explicit ACTIVE v4/v5 preparation |
| `p1-business` | `conversation-agent` | `start-business` | Runs with the API in business mode; `stop-business` returns the API to ordinary M1 mode |
| `p1-models` | `p1-llm`, `p1-stt` and `p1-tts` | `start-models`; also `start-local-real` | Cached model sizes and digests are checked before engines start |

### Resource limits

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Core memory | 1,792 MiB aggregate | Core lab (five services) | Allow roughly 2 GB of free Docker memory |
| Business memory additions | 256 MiB durable worker, 512 MiB native conversation and 256 MiB Jaeger | Business profile | 2,816 MiB configured total before Docker, build and browser resources |
| Model service ceilings | 5.5 GiB and 10 CPU | Local-real model services, on top of the configured business stack | The core-only 2 GiB guidance is insufficient |
| H1 workload container caps | 1000 millicores, 512 MiB and a pids limit of 128 | H1 workload API and each worker | Not measured requirements or production capacity |

These are configured ceilings. Actual usage and production sizing need
measurement. [Design.md](Design.md#non-functional-requirements) lists the
per-service limits.

### Image pins

[images.env](images.env) and [images.lock.json](images.lock.json) are the
authoritative pins: each selection is a versioned upstream image with its registry
digest, and `doctor` validates the pinned images. The selections are:

| Setting | Pinned image | Used by |
| --- | --- | --- |
| `LIVEKIT_IMAGE` | `livekit/livekit-server:v1.13.11` | `livekit` |
| `POSTGRES_IMAGE` | `postgres:18.6-bookworm` | `postgres` |
| `PYTHON_IMAGE` | `python:3.14.10-slim-bookworm` | The shared Python image for `control-api`, `rtc-agent`, `p1-migrate`, `p1-worker` and `conversation-agent`, and the `p1-stt` and `p1-tts` engine builds |
| `NODE_IMAGE` | `node:26.13.0-bookworm-slim` | The console build stage |
| `NGINX_IMAGE` | `nginxinc/nginx-unprivileged:stable-alpine3.24` | The console runtime |
| `JAEGER_IMAGE` | `jaegertracing/jaeger:2.23.0` | `jaeger` |

The [local-real operations guide](../docs/local-real-inference.md) owns the local
engine selections.

### Published ports

Defaults bind every published endpoint to loopback. The settings in
local-setup/.env change the host ports.

| Endpoint | Default address | Setting |
| --- | --- | --- |
| Browser console | http://127.0.0.1:13000 | `UI_PORT` |
| Control API readiness | http://127.0.0.1:18080/readyz | `API_PORT` |
| LiveKit signalling/API | http://127.0.0.1:17880 | `LIVEKIT_HTTP_PORT` |
| LiveKit ICE TCP / UDP | 17881 / 17882 | `LIVEKIT_TCP_PORT` / `LIVEKIT_UDP_PORT` |
| PostgreSQL | 127.0.0.1:15432 | `POSTGRES_PORT` |
| Optional tracing UI | http://127.0.0.1:26686 | `JAEGER_UI_PORT` |

Opt-in tools use these additional loopback addresses:

| Tool | Address |
| --- | --- |
| Phase G browser gate | Owned loopback ports 13001 and 18081 |
| Joined showcase UI | http://127.0.0.1:5179/channel-policy.html |

### Report and state locations

Paths that start with local-setup are inside this directory. Paths that start
with .local are relative to the repository root and are ignored by version
control.

| Path | Contents |
| --- | --- |
| `local-setup/.env` and `local-setup/.secrets.env` | Ignored nonsecret settings and the private mode-0600 credential file, both created by init |
| `local-setup/.generated` | The secret-free LiveKit configuration rendered by init |
| `.local/business-bootstrap` | The private empty SQLite source and backups created by prepare-business |
| `.local/validation/p1-phase-c/postgres-gate.json` | Explicit PostgreSQL lane report |
| `.local/validation/p1-phase-e/container-demo.json` | Phase E demo report |
| `.local/validation/p1-phase-h/<run-id>` | H1 workload reports |
| `.local/validation/p2-postgres` | P2 intake, dispatch, gateway and agent reports |
| `.local/validation/p3-coordinator`, `.local/validation/p3-execution` and `.local/validation/p3-completion` | P3 coordinator, execution and completion reports |
| `.local/validation/p2-channel-origin` | Original channel-input reports |

## Next milestone

Current work focuses on repeatable joined lifecycle and release evidence. The
[H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) retains the
completed inquiry measurement; it is a regression baseline rather than an
unfinished implementation milestone.

| Step | Outcome | Gate |
| --- | --- | --- |
| Retain and reproduce the S-I06/P1-I27 local inquiry baseline | The completed H1 measurement, inspected results and limits stay reproducible | The [declared inquiry workload](#declared-inquiry-workloads) pass criteria |
| Run the actual browser regression under Phase H | Closed Phase G evidence is preserved | The [Phase G business browser gate](#phase-g-business-browser-gate) |
| Keep evidence kinds apart | Transport, persistence, local scripted media and actual-model evidence stay distinct | Each kind keeps its own [validation](#validation) lane |

The following work remains outside the qualified scope and keeps its own gates:

| Remaining work | Gate |
| --- | --- |
| The optional local_real profile and physical quality, which remain unqualified | Actual headroom and engine, model and browser qualification ([local-real operations guide](../docs/local-real-inference.md)) |
| Complete P2/P3 acceptance | The full channel, delegation and release gates |
| Full joined discovery/restart, installed/container reproduction and media qualification beyond the selected journeys | The [joined work item](../docs/work-items/0045-joined-native-channel-policy.md) gates |
| Fresh lifecycle drain qualification after the ordering repair | [Lifecycle follow-up](../docs/work-items/0050-lifecycle-drain-and-documentation-cleanup.md) |

A build, a successful plan or a healthy service alone cannot qualify any of these.
[Acceptance and qualification status](#acceptance-and-qualification-status)
records what has passed.
