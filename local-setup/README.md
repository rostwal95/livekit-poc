# Local ecosystem setup

Status: Active
Last reviewed: 13 November 2026

## Overview

Run the isolated development foundation on Docker Desktop or a Linux Docker
engine. Infrastructure includes a self-hosted LiveKit server, PostgreSQL, an
operator control API, a deterministic Agents SDK worker and the browser console.
An optional profile adds a local tracing backend. A separate one-shot profile
prepares the P1 PostgreSQL schema. No model or carrier keys are needed for the
transport lab or the deterministic inquiry tests.

## Implementation status

The default five-service profile exposes SQLite M1 intake, room-scoped tokens and
a diagnostic worker that echoes text and counts real received audio frames. That
worker performs no STT, model reasoning, TTS, SMS or specialist analysis.

Explicit P1 profiles add PostgreSQL v4 managed admission, case/consent/effect and
completion authority, DB-time leases and an independent bounded pull worker. The
p1-business profile composes these with a scoped current-case workspace, separate
exact human quote approval, native scripted AgentSession and filtered local OTLP.
Preparing roles/schema alone never switches the original M1 volume or enables
business mode. See the [conversation guide](../docs/conversation-and-showcase.md)
and [Phase G evidence](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md).

P1-01 through P1-05 retain their executable SQLite acceptance/recovery scope. The
separate PostgreSQL and phase lanes use isolated synthetic state for their
declared assertions. The harness catalog owns current complete registrations;
P3-01/P3-03/P3-11 have registered passing local lab reports; all 17 P2 and remaining 14
P3 rows stay planned. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending.

### Optional native/deadline composition

The [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
adds an isolated p2-native.html build and host SDK/gateway/browser exercise against
local Docker LiveKit/PostgreSQL. Default M1/P1 UI, services and persistent state
remain unchanged. Explicit owner v6 setup adds two native tables while preserving
old channel identities. The scripted profile needs no provider keys. Selected
six-group actual native and installed Python/npm artifact gates passed; final selected phase
checks and the affected media rerun passed. P3's selected source/installed
eighteen-case deadline gates and forty-six compatibility assertions passed without
production runtime changes.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the
[ecosystem scope](../docs/portfolio-scope.md), [build plan](../docs/build-plan.md),
[technology baseline](../docs/technology-baseline.md) and
[validation plan](../docs/validation-plan.md). Image versions and registry digests
are recorded in images.env and images.lock.json. The
[Phase C work item](../docs/work-items/0009-p1-phase-c-postgres-cutover.md) records
the actual PostgreSQL validation results and remaining limits.

### Development-only workspace members

Frozen host development setup includes the P2 channel-contract codec and P3 native
baseline packages for their explicit tests. They are root development dependencies.
The Python image copies their workspace build metadata for frozen lock validation
but installs only the existing application/P1 production dependencies with no dev
group. The console image sees the P2 manifest for frozen workspace resolution and
builds only the console. P2's bounded gateway/owned scripted-agent process and
P3's issued runner/delivery/action clients remain opt-in host library/process
paths; ordinary Compose/UI startup does not compose them. The P1 work v2 issued
execution, v3 delivery/action and v4 result-feed owner upgrades are explicit and separate from
booking v4; serving code performs no DDL. Guarded work/case actions require the
same supported PostgreSQL target with separately verified schema/credential
bindings. The independent result receiver owns private local receipt storage,
not execution state. The explicit P2 case bridge is local application composition
with preconstructed credential-bound P1 clients and finite trusted mappings; it
loads no configuration or credentials and starts no listener on import. It adds no
P1 schema/runtime/dependency change or integrated case copy. No P2/P3 service, model
download or provider call starts implicitly.

### Revision routing and selected P3 acceptance

P2-I10's explicit RevisionRouter decodes a strict investigation command from
already accepted authenticated inbox input. Choose the owner-installed standalone
reference PostgreSQL case authority or public P1 CAS through the loopback bridge;
never run both as authorities for the integrated case. Existing P1 v4 is unchanged.
Lost revision ACK remains unknown without a command receipt or automatic retry/
rebase. Retained inbox reads authorize account history, not current sender
association. The separate linked-confirmation router now rechecks original current
association before a new call; atomic cross-store revocation remains unqualified.

The selected 22-case dual-authority gate has passed. With the existing local
restricted-role PostgreSQL setup and pinned host Node, run from the repository root:

```sh
make p2-routing-check
make p3-contract-check
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

P3's selected registered lab assertions are 13/8/12; required setup, exact inventory,
report freshness and owned process/schema/socket cleanup are mandatory. Default
Compose/UI still serves the existing foundation/business paths. These gates add
no paid provider call, native audio, real carrier, image decoding or full release.

### Qualified linked-consent and result-projection slice

The [phase handoff](../docs/work-items/0032-linked-confirmation-and-result-projections.md)
implements a separate opt-in bridge confirmation capability and explicit host
projection tooling. Selected local qualification passed. A trusted
controller prepares exact P1 quotes; immutable P2 prompts preserve the original
canonical bytes and UUID5 proposal identity. Only explicitly linked user consent
and the fixed configured mapping reach public commit_confirmation. Its original
command receipt can reconcile a lost ACK through explicit replay. Revision CAS
remains a different capability without that receipt. No quote/confirmation tool
is exposed to the model, and the bridge does not atomically fence P2 revocation.

Work-profile v4 is an explicit owner-only v3 upgrade, separate from booking v4.
It adds a stable source UUID, scoped result events and cursors; runtime performs
no DDL. P3 separately initializes bounded metadata/checkpoints and reads original
results through public ports. Stored applicability is immutable as-of evidence,
not refreshed current truth, delivery or action permission. Serving defaults,
provider keys, named volumes and ordinary Compose/UI composition stay unchanged.

### Qualified selected outbound-reply and completion-processing slice

The [completed phase](../docs/work-items/0033-outbound-replies-and-completion-processing.md)
adds locally qualified explicit host tooling. Its 24-case P2/16-case P3 gates
and isolated installed consumers passed without adding a default daemon.
P2 owner-upgrades its inbox profile to v3 for immutable-recipient replies and
versioned route/suppression checks. Carrier I/O remains outside SQL after guarded
possible-send reservation. An attempt with no known result remains unknown, not an automatic retry; later
route changes cannot retarget the original attempt. Ordinary carrier acceptance
is distinct from delivery and human acknowledgement.

P3 owner-upgrades its projection profile to v2 without changing P1 work v4. Its
bounded explicit processor retains a scan cursor and separate contiguous terminal
ACK watermark. An unknown event remains unacknowledged while a later eligible
result can progress. Exact known original receipts survive restart/cancellation;
processing has no source ACK, action or consent authority. Existing possible-send
absence stays lookup-only. Default Compose/UI, provider credentials and named
volumes remain unchanged; no automatic booking-completion handoff is added.

### Current send-policy and protected-action validation

The [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. P2 policy APIs
require explicit owner inbox v4-to-v5 maintenance/quiescence and preserve all old
request/result/callback bytes. Ordinary possible sends remain held. A separately
trusted cooperating provider may reuse frozen original operation bytes/key only
under a new explicit recovery-controller command and current permission. Retain
callback exact-attempt correlation and vetoes; never retarget the original address.
P3's new gate uses unchanged public work v4/booking v4 guards and independent
supplier fixtures, with no projection upgrade or new daemon. Its 31 modes/16 cases
require two prewarmed SQL waiter graphs and three owned kills under a 180-second
total budget: 165 seconds work and 15 seconds cleanup. With the documented
restricted-role setup, make p2-send-policy-check and make p3-action-races-check
passed their selected synthetic backend gates. Existing callback/applicability commands
retain the previous checkpoint's passing scope. No provider key, default Compose/
UI change, named-volume reset or automatic booking-completion handoff is added.

### Previously qualified callback and applicability profiles

The [completed phase](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
completed selected local phase gates for P2-I13 and P3-I11. Callback APIs require explicit owner inbox v4 setup;
P3 refresh/display metadata requires an explicit owner projection v3 upgrade.
P1 work v4 and booking v4 remain unchanged. No new default daemon, Compose/UI
route, provider credential or paid call is introduced.

Callbacks authenticate a separate raw-byte HMAC capability and correlate exact
old attempts independently of current sender association. Their evidence cannot
open a resend. Refreshed applicability uses explicit per-result CAS and separate
as-of source/case/time observations; hiding display preserves all identities and
unresolved processing. Callback bytes are capped at 4096; the signature window
is 60 seconds and is rechecked against database time after admission. Callback
bounds default to 10000 total/eight per attempt, maximum 100000/32. Refresh commands default to 3000 total/four per event,
maximum 30000/eight, with receipts at most 4096 bytes. Equal replay remains
available at capacity for the profile lifetime; no physical deletion or capacity
reclamation exists. The isolated role-separated actual gates and offline installed
consumers passed their selected assertions; existing quickstarts retain their qualified scope.

## Requirements

Use the selected Python 3.14 runtime for the dependency-free lifecycle manager, Docker Engine and
Compose 2+. Docker builds supply pinned Python and Node runtimes; host Node and
LiveKit installations are unnecessary for the core Docker route. The optional
actual browser gate below also needs host Node, pnpm and the pinned Playwright-managed Chromium. Allow roughly 2 GB of free
Docker memory for the core lab plus image/build disk space. Existing workloads
need their own capacity. Initial builds require internet; the transport lab uses
local services after images and dependencies are available.

Defaults bind all published endpoints to loopback:

| Endpoint | Local address |
| --- | --- |
| Browser console | http://127.0.0.1:13000 |
| Control API readiness | http://127.0.0.1:18080/readyz |
| LiveKit signalling/API | http://127.0.0.1:17880 |
| LiveKit ICE TCP / UDP | 17881 / 17882 |
| PostgreSQL | 127.0.0.1:15432 |
| Optional tracing UI | http://127.0.0.1:26686 |

The browser and container signalling URLs differ. ICE configuration preserves
loopback and internal candidates so actual browser/container media must be tested.
No Linux-only host-network mode is assumed. LAN/mobile access and remote TLS/TURN
are separate deployment work; the local manager fixes the published address to 127.0.0.1 to match token URLs
and browser connection policy. Host ports remain configurable. The control API
also exposes bearer-protected /api/metrics; see the
[observability contract](../docs/observability.md).

### Python runtime bytecode

The shared [Python image](docker/python.Dockerfile) installs frozen production
extras and the workspace without editable imports, using uv sync with
--compile-bytecode in the build stage. The runtime retains those installed caches
and keeps PYTHONDONTWRITEBYTECODE=1; children do not need to write caches at startup.
Rebuild the shared image after relevant Python or dependency changes before actual
workload/media gates. Bytecode changes import preparation, not business authority,
model selection, worker concurrency or operation deadlines. Retain image/source
provenance; it is not a throughput or stable latency guarantee.

## Commands

Run from the repository root using the selected Python 3.14 interpreter:

```sh
python3.14 local-setup/stack.py init
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py config
python3.14 local-setup/stack.py start
python3.14 local-setup/stack.py status
python3.14 local-setup/stack.py smoke
```

Init creates ignored .env and private mode-0600 .secrets.env. Credential schema v2
adds POSTGRES_MIGRATION_PASSWORD to the complete known v1 inventory atomically;
all five existing values, custom endpoints and the volume-owner identity stay
unchanged. Repeated init preserves the upgraded file. Unknown/incomplete schemas,
unsafe files and concurrent initialization fail before replacing credentials.
Other actions require this explicit upgrade and do not generate missing secrets.

Init renders a secret-free LiveKit config under .generated. Config validates
Compose without printing expanded secrets. Start uses a bounded build and
health/readiness wait. The lifecycle manager checks checkout
ownership before mutating existing same-name containers, and credential-derived
owner labels before reusing or deleting persistent volumes. Retain private local
credentials with their volumes; regenerating them does not adopt existing data.

### Isolated stack per checkout

Set STACK_PROJECT in local-setup/.env to give a checkout its own Compose project,
container, volume and image names (default livekit-agent-ecosystem; lowercase
letters, digits and hyphens, 3–41 characters). Change UI_PORT, API_PORT,
LIVEKIT_HTTP_PORT, LIVEKIT_TCP_PORT, LIVEKIT_UDP_PORT, POSTGRES_PORT and
JAEGER_UI_PORT as well when another stack already uses the defaults. The
lifecycle manager only mutates containers labelled for the current checkout and
project, so a second stack never touches the first. Run init before start in the
new checkout; it generates separate credentials.

### Joined showcase profiles

`make channel-policy-demo-setup CHANNEL_POLICY_PROFILE=<new directory>` runs two
owner steps: `channel_policy_setup.py prepare` creates the profile's disposable
schemas and private configuration, and `associate-sms` links the fixed synthetic
SMS sender with a signed LINK challenge so simulated SMS is accepted. Both need
the stack started and `prepare-postgres` done. A profile holds sixteen inputs;
prepare a new directory for each fresh demonstration. The root README covers
start, provider mode and recording.

### PostgreSQL role and schema preparation

After init and start, run the same commands for a fresh or retained database:

```sh
python3.14 local-setup/stack.py prepare-postgres
python3.14 local-setup/stack.py migrate-postgres
```

Prepare-postgres runs a bounded bootstrap inside the existing PostgreSQL container
after its normal TCP server is healthy. The bootstrap administrator stays inside
that container. It creates the restricted continuity_migrator login when absent,
checks managed role attributes and verifies both retained passwords through TCP
SCRAM authentication. It resumes an interrupted pending creation and refuses an
existing credential or policy mismatch without rotating a password. Start alone
does not perform this role operation.

Migrate-postgres runs the optional migrations profile's p1-migrate service once
with only the migration credential. The serving API receives the existing runtime
password, and the agent receives neither migration nor bootstrap credentials.
The runtime role cannot create schemas/tables, use temporary tables or change
migration metadata. The migration role has CONNECT and CREATE on livekit_lab;
application table ownership/grants are installed by the versioned schema command.

This command prepares a **staging schema only**. It does not import a source,
activate the target, mount the M1 application volume or switch the serving API.
Standalone cutover requires an explicit source path, private backup and the
ordered quiesce/import/verify/source-checkpoint/activation procedure. Use
make postgres-check below for an isolated executable demonstration; preserve
the live M1 volume. Do not source .secrets.env or invoke expanded Compose config
to obtain credentials.

### First persistent P1 business workspace

Run from the repository root after make bootstrap and the ordinary init/start
commands. Docker must be running. This host-only preparation uses the frozen
.venv interpreter and the validated private local settings; do not source secrets
or put credentials in arguments:

```sh
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-business
.venv/bin/python local-setup/stack.py worker-status
```

prepare-business is an explicit owner operation for the configured P1_WORKER_SCHEMA.
make business-setup runs the same action. Its host work deadline is 90 seconds
inside a 120-second owned child supervisor. Failure retains private recovery
artifacts and reports a fixed stage/code; reset is not a recovery step.
For a fresh empty target, it creates a separate empty SQLite inquiry source under
ignored private .local/business-bootstrap, preserves its backups, runs the actual
quiesce/import/verify/checkpoint/activation protocol and applies v2, v3 and v4 in
order. The original application_data/intake.sqlite3 M1 database is never its source.
It neither switches the M1 API backend nor creates supplier fixtures or consent.
An existing valid ACTIVE v4 target is checked without importing old source over
current business rows. Conflicting, nonempty or unowned staging state is refused;
inspect and retain it rather than deleting state to force startup. Retain the
whole private bootstrap folder, source, backups and existing credentials for
recovery. Do not replace the source or change the selected endpoint/schema during
an unfinished preparation.

init-worker-fixtures separately creates the same-scope synthetic supplier and
completion receiver in the retained worker_data volume. Repeating initialization
preserves their provider/receiver identities and existing booking state. It does
not grant mutation consent. Use the same P1_WORKER_SCHEMA and P1_WORKER_SCOPE for
preparation, fixtures and runtime; defaults are continuity and demo-traveller.
Normal start/stop preserves these named volumes and accepted work.

For local real inference, complete this same authority/fixture setup, explicitly
prepare the pinned model cache, and use start-local-real in place of start-business.
Follow the [local-real operations guide](../docs/local-real-inference.md) for exact
model/image preparation, browser setup, resource headroom and inference limits.
The cache and healthy engines alone do not qualify actual inference or media.

migrate-postgres remains the staging-only schema command for explicit migration
work; it is not a substitute for prepare-business. PostgreSQL and phase demos
create and clean their own isolated schemas. Passing them does not prepare the
normal persistent workspace. Existing older ACTIVE schemas with application data
retain their original controlled migration history and explicit ordered upgrade
procedure; they must not be replaced with the empty bootstrap source.

Open the browser console and retrieve the operator token explicitly:

```sh
python3.14 local-setup/stack.py token
```

Paste the token into the console's password field. It stays in browser memory;
it is not embedded in the build or saved to browser storage. Connect to a lab
room, send text and enable the microphone only with its explicit button. The
agent returns deterministic diagnostics rather than an AI answer.

```sh
python3.14 local-setup/stack.py logs
python3.14 local-setup/stack.py logs --service rtc-agent
python3.14 local-setup/stack.py start --observability
python3.14 local-setup/stack.py stop --observability
```

The optional profile verifies the tracing UI returns HTTP 200 and uses in-memory
storage. The explicit business profile also exports filtered application/native
traces. UI readiness alone does not establish export coverage or retained
production telemetry. Normal stop removes this project's containers/network and
preserves named volumes. Reset is intentionally separate:

```sh
python3.14 local-setup/stack.py reset --observability --confirm RESET_LOCAL_STACK
```

Reset deletes only this project's volumes and synthetic state. Never use it to
perform a normal restart. Changing database credentials on an initialized volume
requires a separate explicit role/password operation. Init upgrades only the
known credential inventory, and neither role preparation nor normal restart
rotates existing passwords. Reset is not an upgrade procedure.

Log output retains a redacted bounded tail from stdout and stderr. Select a known
service with logs --service rtc-agent when the combined tail obscures its events;
--service is valid only for logs. Selection does not increase the output budget.

For the standalone Phase D demonstration, rebuild using start, then run
make phase-d-demo. It uses only owned synthetic schemas and two disposable
runtime containers. The [guide](../docs/case-and-continuation.md) defines setup,
exact confirmation, deadline and cleanup behavior. upgrade-postgres runs an
explicit owner-only ACTIVE-v1-to-v2 upgrade; STAGING is refused and the live M1
API backend is not switched. migrate-postgres remains initial v1 preparation.

### Confirmed mutation and completion demo

After rebuilding with start and preparing the two database roles, run:

```sh
make phase-e-demo
```

The host creates and removes one UUID-owned PostgreSQL schema and labelled
fixture volume. Five fresh installed-runtime containers seed the same supplier
for inquiry/apply, stop after supplier commit, reconcile and cancel, stop after
receiver commit, and verify replay plus diagnostic pruning. Runtime containers
receive only the restricted runtime credential. The temporary root container
only initializes ownership of this invocation's checked fixture volume; the
application runs as the existing unprivileged user with resource limits.

The [effects guide](../docs/effects-and-completion.md) describes identities,
confirmation, uncertainty, cancellation and retained receipts. The resulting
.local/validation/p1-phase-e/container-demo.json is written as passed only after
owned cleanup. The demo preserves M1 state and needs no provider account.

For an existing **ACTIVE v2** standalone schema, upgrade-effects explicitly runs
owner-only schema v3. First upgrade ACTIVE v1 with upgrade-postgres. Staging is
refused; migrate-postgres still prepares initial v1. These operations do not
activate/import a source or switch the API. Keep schema backups and migration
credentials with the documented isolated operator procedure.

### Leased durable worker profile

Normal start still starts M1 and transport diagnostics. The opt-in p1-workers
profile adds the actual P1 worker with an independent worker_data fixture volume.
For an intentionally activated v3 target, run upgrade-coordination to install
v4. A fresh migrate-postgres target is STAGING and cannot start a worker. The
migration refuses unmanaged running legacy inquiries: reconcile them on v3 first.

Optional non-secret .env values P1_WORKER_SCHEMA and P1_WORKER_SCOPE select the
worker/migration schema and trusted worker scope; defaults are continuity and
demo-traveller. Existing configuration remains valid and credentials are retained.
This does not change the live M1 SQLite backend or activate a source automatically.
For a fresh persistent workspace, first follow [business preparation](#first-persistent-p1-business-workspace).
After explicit ACTIVE v4 preparation or the existing controlled upgrade, operations are:

```sh
python3.14 local-setup/stack.py init-worker-fixtures
python3.14 local-setup/stack.py start-workers
python3.14 local-setup/stack.py worker-status
python3.14 local-setup/stack.py logs --service p1-worker
python3.14 local-setup/stack.py stop-workers
```

Fixtures are synthetic supplier and completion-receiver files, explicitly created
as the runtime user. Initialization neither installs nor activates PostgreSQL.
Keep them with their named volume so provider/receiver identity and receipts
survive normal restart. The worker has no migration/bootstrap credential, HTTP
port or Docker socket. Stop/reset includes the opt-in profile; normal stop
preserves all three application/database/worker volumes. Reset remains destructive
and requires its existing explicit confirmation.

Run make phase-f-demo after rebuilding and preparing database roles for an isolated
installed-runtime demonstration. It owns a separate schema and labelled fixture
volume, uses the actual worker profile, restarts a persisted wait, drives explicit
confirmation and completion, and proves progress after admission pressure.
Passing evidence is written only after owned cleanup. See the
[lease and worker guide](../docs/leases-and-workers.md) for exact semantics.

### Optional provider inference

The trusted native mode is exactly scripted (default), local_real or provider_real.
The provider profile needs no local engines or model cache. Its authoritative
[operations guide](../docs/provider-demo.md) documents make provider-setup,
make provider-check, make provider-start, make provider-stop and the explicit
P1_ACCEPTANCE_REAL_PROFILE=provider_real acceptance selector. All three keys are
validated privately and forwarded only to the native service. The persistent
ACTIVE v4 workspace and fixtures remain separate explicit prerequisites.
The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.
The joined showcase reuses the same private file: `make channel-policy-demo-start-provider`
reads it with the strict loader and passes the keys only to each room's native
worker. local-setup/.env.providers.example lists the three key names.

### P2 verified PostgreSQL intake check

After the ordinary local init/start/prepare-postgres and frozen Python/Node/pnpm
setup, run make p2-postgres-check from the repository root. This explicit lane
uses the existing settings loader privately, fixed loopback/database roles and
fresh marked P2 schemas. It compiles source with pinned TypeScript, then tests
actual HMAC association, durable input, concurrency, drift and process recovery.
No P1/P3 service, carrier account, provider key or hosted resource is required.
It never resets a volume or replaces the existing application schema.

For retained evidence, use local-setup/scripts/p2_postgres_check.py --report with
a fresh filename under .local/validation/p2-postgres. Existing reports are not
overwritten. Raw child capture is bounded/private and removed after inspection;
cleanup failure, missing setup, zero tests or skips cannot pass. This is disposable
intake qualification, not a started P2 gateway or a persistent user workspace.
The local runtime role is shared with P1, so separate DB-principal isolation is
not established by this test. Do not expose a P2 service before that separation
and the later authenticated HTTP/runtime gates are qualified.

### P2 standalone and P3 local HTTP examples

From the root after frozen bootstrap, run make p2-demo for only the two actual
P2 public-example/process-replay cases. It requires the same explicit local
PostgreSQL preparation as the full lane above; wrapper --example selects those
cases without changing ordinary setup. The demo owns disposable schemas and
runtime-only child credentials and closes them before returning a safe report.
The preview explicitly reports pending input and not_executed business work.

Run make p3-demo for a provider-free scripted policy request through a real
loopback server and typed client. It builds the specialist package, creates an
ephemeral listener and synthetic bearer/evidence, prints the bounded candidate
observation and closes its client/server. It needs the pinned Node/pnpm environment,
not PostgreSQL, P1/P2 services or provider keys. Neither command starts a persistent
product service, modifies the existing application case or qualifies UI/media.

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
The [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md) owns exact evidence and prerequisites.

### Active workload and standalone image gates

The [completed handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records passing selected P2-I19/P3-I16 qualification. Use the frozen Python 3.14.10/Node
24.22.2 host toolchain and existing caches. From the repository root:

```sh
make p2-workload-plan
make p3-document-plan
make p2-workload-check
make p3-document-check
make p3-document-package-check
```

Plans start no workload. The P2 check uses ordinary restricted-role local PostgreSQL
settings and fresh owned v7 profiles: retained limits 64/1,024, seed 39, and dormant
samples 0/64/256/1,000 with public setup/read windows at most 64. It changes no
schema version or default service and allocates no agent/room per dormant case.
The selected two-gateway phase declares at most eight runtime SQL connections and
sixteen retained runtime SQL operations, plus two simultaneous owner control
connections (ten combined). Its 360-second total includes twenty cleanup seconds.
Selected workload qualification passed; resource samples describe the configured
local profiles and do not establish production capacity. Never reset existing data to run this study.

Image source checks use owned loopback HTTP and fixed worker threads, without
PostgreSQL, rooms, provider settings or models. Installed mode builds fresh current
Python/npm artifacts through the maintained offline package builder, then runs the
same twenty declared image cases outside the checkout. Sources and the independent
literal oracle are copied as explicit consumer setup; public examples load none
implicitly. Source/installed bounds are 120/360 seconds including twenty cleanup
seconds and a shared ceiling of thirty-two process children. Actual PNG bytes are
bounded to 2 MiB/2048×2048 and checked before the scripted provider. The supported
RGB8/RGBA8 noninterlaced subset is intentionally narrower than full PNG.

Reap actual owned children/groups before deleting their private work. Worker/provider
settlement and public close retry are separate from cancel ACKs. Preserve failed
attempts and bounded finite diagnostics. These gates perform no OCR, paid inference,
P1 durable image work/action or default-stack deployment; missing setup is non-passing.

### Result receiver qualification

From the repository root, `make p2-result-receiver-plan` prints the finite
sixteen-storage/four-return schedule. `make p2-result-receiver-check` uses isolated
owner/runtime PostgreSQL profiles, one scheduled receiver-caller kill and actual
backup/restore; it creates no room, provider call or carrier send.
`make p2-result-receiver-package-plan` and `make p2-result-receiver-package-check`
run the separate offline archive/installed lane: twenty-five owned groups, eight
existing package assertions and twenty copied fake-port tests. That lane claims
zero actual storage/return assertions. The [work item](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
records prerequisites, exact outcomes, retained failures and full-phase status.


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
schedule. See the [origin work item](../docs/work-items/0044-origin-bound-channel-policy.md) for exact scope, failures and evidence.
Integrated browser voice/text/SMS, provider composition, restart discovery and the
final demo video remain separately gated.

## Validation

Doctor validates required files, private credential permissions, pinned images,
Docker availability, Compose rendering, checkout ownership and free ports before
a fresh start. Smoke checks real dependency readiness, operator authentication,
M1 replay/conflict, named-agent dispatch, native text and fixture audio reception.
It does not certify the three product V1s or actual model behavior.

Unit tests use isolated temporary fixtures:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_local_setup.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_control_api.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_rtc_agent.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_authorization.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_source_transfer.py' -v
```

### Explicit PostgreSQL lane

Install the frozen root environment with local/agent extras, then complete
init, start and prepare-postgres. Run from the repository root:

```sh
make postgres-check
```

The checker reads private setup credentials as data, clears ambient PostgreSQL
target selectors and creates/removes only its own isolated schemas and synthetic
source/backup/supplier fixtures. It exercises actual PostgreSQL transactions,
runtime privilege refusals, staging/activation, interrupted recovery and scoped
application access. It never starts or resets the stack or cuts over the live M1
database. Missing setup/database, failures, timeouts and skipped cases remain
non-passing. Its machine report is
.local/validation/p1-phase-c/postgres-gate.json. Ordinary unit discovery is an
offline lane and cannot substitute for this gate.

The diagnostic worker admits one active room within its local memory budget.
End browser sessions before smoke; the command creates its own room and does not
terminate another active session to obtain capacity.

For host-side tests install the frozen root environment described in the root
README. Lifecycle stdout is structured and secret-redacted. Keep runtime reports
under ignored .local and inspect service logs when a readiness/smoke stage fails.

### Declared inquiry workloads

The H1 S-I06/P1-I27 controller is an explicit opt-in measurement tool, separate
from normal startup, smoke and the acceptance catalog. The
[H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) records the
completed local inquiry measurement and its limits. Freeze the reviewed
[versioned manifest](../harness/workloads/p1-inquiry-v1.json) before measuring:

```sh
make p1-benchmark-plan
```

This validates the default manifest and prints its canonical digest, six experiment
names and status not_started. It starts no Docker workload and is not measurement
evidence. The equivalent CLI is .venv/bin/python local-setup/scripts/p1_benchmark.py;
--manifest selects an explicitly reviewed bounded local manifest. Changing a
schedule or budget requires a new reviewed declaration, not relabelled results.

Actual execution requires the frozen local environment, the owned foundation
network/PostgreSQL service and prepared restricted migration/runtime roles, plus
a freshly built shared Python image matching inspected source. Use the existing
init/start/prepare-postgres procedure above. The runner creates and upgrades its
own empty UUID-owned schema; it never selects the application schema or M1 data.
After setup and manifest review, execution is explicit:

```sh
make p1-benchmark
```

This invokes .venv/bin/python local-setup/scripts/p1_benchmark.py --run. It starts
installed API/worker containers without checkout mounts, verifies installed-source
provenance and configured cgroup limits, and owns separate supplier/receiver and
API volumes. Existing stack credentials are read privately, not sourced as shell
code or copied into retained evidence. Only the owned schema/fixtures are cleaned.
Missing setup, useful progress, independent receipts or owned cleanup is non-passing.
The isolated inquiry environment does not enable native media or OTLP trace export;
its HTTP/worker observations are separate from the G trace/media lane.

| Frozen declaration | Meaning before an actual run |
| --- | --- |
| Six modes | steady-w1/w2: 20 offers at one-second spacing; burst-w1/w2: 32 offers; saturation-w1/w2: 32 staged offers with workers initially stopped |
| Expected new-work totals | 168 offers, 120 admissions and 48 capacity rejections; declarations, not observations; replay/GET/cancel calls are separate |
| HTTP pressure | One shared concurrency slot in steady modes, four in burst/saturation; submit, replay, GET and cancellation use the same semaphore/pool |
| Saturation | Admit eight, prove original-key read/replay at capacity, reject 24 new identities, then start workers with active cap one |
| Resources | API and each worker: 1000 millicores, 512 MiB and pids limit 128; these configured caps are not measured requirements or production capacity |
| Time/evidence bounds | 180 seconds/experiment within a 600-second run, bounded 90-second owned cleanup and at most 4096 raw records; request network timeout at most five seconds within remaining budgets |

Case observation performs one global round-robin GET, then sleeps 250 ms. HTTP
and shared-slot waiting add delay; this is neither a 250 ms per-task refresh nor
a hard tick. Scheduled offer, first HTTP start, known validated acknowledgement
and first validated successful inquiry snapshot remain separate. A successful
submit/replay projection can be the first result observation. Unknown HTTP
attempts record their finish time without claiming an acknowledgement. Reported
result latency includes caller queueing and observer lag, not an exact supplier
completion instant.

Resources are sequential docker-exec Python cgroup-v2 probes at a one-second
target cadence. Evidence retains actual probe start/end/duration and skipped
intervals; a missed slot is not caught up with back-to-back probes. The observer's
in-container CPU, memory and PID overhead is included. memory.current is accounted
cgroup memory, not RSS or a peak; pids.current counts kernel tasks/threads. CPU
records use cumulative microseconds with observed first/last/delta/window. The
resource window includes post-inquiry replay/cancellation/delivery checks. Host,
Docker VM, shared PostgreSQL and outside-cgroup overhead are excluded. See
[measurement semantics](../docs/observability.md) for cap-versus-usage and clock rules.

Reports under ignored `.local/validation/p1-phase-h/<run-id>` retain the frozen
workload, bounded safe raw records and source/image/machine provenance. A
`<experiment>.measurement.json` snapshot precedes cleanup; its measured status is not a passing
phase. Per-experiment/aggregate pass requires independent inquiry reconciliation,
unchanged booking/zero supplier mutations and verified owned cleanup. Preserve
failed records, separately recorded cancellation/outcome/delivery and closed G
artifacts. Before temporary capture files are removed, each original failure
retains a fixed-enum code/operation and any observed exit code, timeout flag,
command budget and elapsed time. Cleanup failures are recorded separately. Raw
argv/stdout/stderr, environment values, bodies and exception text are not retained
in public failure diagnostics.

The controller automatically reports host system/architecture/Python and installed
runtime architecture/versions. Docker-VM CPU/memory and shared-host context require
separate operator collection; a supporting environment.json is not automatic
runner output. Summaries use sample count/minimum/median/maximum only. This inquiry
slice does not measure media, model quality, physical microphone capture or
production scale. H1 retains its historical inquiry scope; the current H2,
host/Linux artifacts and selected provider_real v2 local P1 release are separately
qualified in the [release handoff](../docs/work-items/0019-p1-phase-h-release-qualification.md).
local_real and physical quality remain unqualified; complete P2/P3 acceptance remains pending.

### Explicit local-real inference

The [local-real operations guide](../docs/local-real-inference.md) owns the new
models-fetch/models-verify, start-models/stop-models and
start-local-real/stop-local-real commands. Ordinary start and start-business retain
their diagnostic/default-scripted behavior. No start action fetches weights,
installs a schema or initializes business fixtures. Ten pinned model files total
2,708,795,741 bytes; their sizes/checksums are checked before engines start.
Models are ignored host cache, not image/build inputs. Runtime engines use an
internal network with no host ports and read-only model mounts.

The model-service ceilings add5.5 GiB and 10 CPU to the configured business stack;
core-only2 GiB guidance is insufficient for this profile. Actual headroom and
engine/model/browser qualification remain separate measurements. A successful
fetch, readiness check or configured badge is not model/media acceptance.

### Cooperative worker pause in isolated gates

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

## Next milestone

Retain and reproduce the S-I06/P1-I27 local inquiry baseline. The
[H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) owns the
completed measurement, inspected results and limits. H2 restart, slow-dependency,
saturation and shutdown measurements passed. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. P1-I26 host/Linux isolated artifacts, typed API/failure review and genuine
native consumer passed, with details in the package work item. local_real and
provider_real implementations exist. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. The optional local_real profile remains unqualified. Full channel/delegation and release gates remain separate. Preserve closed G evidence when running its
actual browser regression under H. Keep transport, persistence, local scripted
media and actual-model evidence distinct. P2-I19 workload/dormancy and P3-I16
standalone document HTTP passed selected local qualification. Selected P2-I20
read/error/telemetry and P3-I17 fixed-policy evidence also passed in 0040;
P2-I21 standalone and P3-I18A durable-v2 selected gates passed in
[0041](../docs/work-items/0041-standalone-channel-and-durable-policy.md).
Selected P3-I18B native RTC text qualification passed in
[0042](../docs/work-items/0042-responsive-native-policy-and-compact-demo.md).

## Business conversation profile

The explicit p1-business profile adds a named native scripted conversation agent.
Its manager commands are start-business and stop-business. The primary workspace
shows current persisted business facts; retained M1 diagnostics remain separate.
Every current-case read is authenticated. Quote preparation is read-only supplier
inspection followed by authoritative publication, and exact confirmation is an
explicit UI command using the unchanged opaque canonical proposal. Native hints,
model text, output playback, Interrupt and End do not grant mutation/cancellation
authority. Before starting, prepare
an ACTIVE PostgreSQL v4 schema through the explicit
[business preparation](#first-persistent-p1-business-workspace) and run
init-worker-fixtures for the same P1_WORKER_SCOPE. The read-only preflight checks
schema/runtime role and existing independent provider/receiver fixtures. It does
not migrate, create fixtures or grant consent. Normal start leaves business mode off.

start-business builds the shared Python image and then starts Jaeger, p1-worker,
conversation-agent and the API with business mode explicitly enabled. The API mounts
worker_data at /business read-only; the native worker has no supplier mount,
operator bearer or migration credentials. Scope/schema reuse the validated optional
worker configuration. The manager supplies the fixed local Jaeger endpoint and does
not accept arbitrary ambient P1_BUSINESS_ENABLED/trace destinations as configuration.

stop-business drains workers with 35-second grace and returns the API to ordinary
M1 mode. Volumes remain. Full stop/reset includes optional profiles, with reset
remaining the separate explicit destructive operation. The configured core aggregate
is 1,792 MiB; business mode adds 256 MiB durable worker, 512 MiB native conversation
and 256 MiB Jaeger, for 2,816 MiB configured limits before Docker/build/browser
resources. Actual usage and production sizing need measurement.

Use the [conversation guide](../docs/conversation-and-showcase.md) for the demo and
make phase-g-demo for isolated actual browser/container/trace qualification. The
host evidence runner also requires the frozen Python and pnpm workspace plus an
prepared Playwright-managed Chromium or an explicit supported executable override.
It owns its test schemas/containers/volumes
and loopback ports 13001/18081; ordinary M1 data is not mounted by the demo.


### Host browser gate and optional automation

The Phase G host runner additionally requires the frozen local/agent Python extras,
a supported host Node runtime and pnpm 12.18.0. The container selects Node 26.13.0. The core
Docker lifecycle does not require these host browser tools. Install the frozen
workspace before running browser evidence:

```sh
npm install --global pnpm@12.18.0
pnpm install --frozen-lockfile
make browser-setup
corepack pnpm --filter @livekit-ecosystem/local-console build
```

Rebuild these host assets after console source changes. Before the browser opens,
the helper verifies that the served index and compiled assets match this host
distribution; the Docker image build does not create the host distribution.

`make browser-setup` explicitly installs the Chromium build selected by the locked
Playwright 1.65.0 dependency. Both browser lanes use that managed browser by default;
starting a gate does not download a browser. A machine's separately installed Chrome
version cannot silently select the default runtime.

On a Linux host that also needs browser system libraries, run
`corepack pnpm --filter @livekit-ecosystem/local-console exec playwright install --with-deps chromium`
instead. A separate Linux host is not a prerequisite for this local POC. After the
four preparation commands above, `make phase-g-demo` uses the prepared managed
browser directly. An explicit existing executable remains available for a declared
comparison; resolve the pinned package's executable and pass it using structured
arguments so paths with spaces remain one value:

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
the prepared local stack; do not provide a real provider account or source private
configuration as shell code. The first-class scripted input uses WebAudio and the
bundled spoken fixture without overriding microphone APIs. This gate establishes
its declared browser, SDK, persistence and trace observations. Input/status
controls require the selected native agent's actual RoomIO-ready attribute plus
active SDK state, rather than participant presence or a delay. Explicit End retires
the media context; the next Join rehydrates the same durable task in a fresh room,
while unknown initial acknowledgements reuse their frozen invocation. Token/task
selection is memory-only; hard reload requires explicit authenticated task resume.

The positive local source is bundled 16 kHz mono PCM through an owned WebAudio
track and actual native SDK/WebRTC. It has bounded creation/publication/close and
late cleanup; unresolved resource ownership blocks another media context. Real
physical microphone permission denial is a separate negative test. Positive device
capture, human hearing, general ASR/model/TTS quality and the complete V1 charter
are not established. Trace/video/HAR recording is disabled, screenshots require
empty password inputs and retained observations use allowlisted bounded fields.

The local-stack workflow declares Phase G after the PostgreSQL, Phase E and Phase F
gates, using the frozen workspace, a host console build and explicit bundled
Chromium. It retains the
existing failure diagnostics and preserve-state stop. The 20-minute job budget has
an estimated 12–15-minute normal workload including the added host/browser setup;
this is a planning estimate, not an observed hosted-run duration. Existing workflow
definitions are optional automation references; remote CI/publication are outside
the local POC scope and do not block P1 completion or P2 work.
See the [Phase G work item](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
for inspected local results and remaining acceptance scope. The action and browser
setup follow the official [setup-node release](https://github.com/actions/setup-node/releases/tag/v7.1.0)
and [Playwright CI guide](https://playwright.dev/docs/ci).

### Durable dispatch and coordinator submission checks

From the repository root after the same frozen local PostgreSQL/Node setup:

```sh
make p2-dispatch-check
make p3-coordinator-check
make p2-gateway-check
make p3-execution-check
make p2-agent-check
make p3-completion-check
```

The P2 selector tests v1-to-v2 owner migration, preserved identities, bounded
claims/attempts, current association and independent-operation acceptance recovery.
It never implicitly upgrades an application schema. The P3 selector explicitly
creates an owned p1_work_ profile through public P1 administration, verifies
immutable coordinator acceptance/replay/cancel and fresh-process reconciliation,
and separately invokes the local TypeScript specialist through Python sockets.
Both gates use synthetic data, runtime-only child credentials and bounded owned
processes; marked schemas and fixtures are removed. Missing setup, skips, timeout,
private child output or incomplete cleanup cannot pass. Fresh report destinations
are respectively .local/validation/p2-postgres and .local/validation/p3-coordinator.

These are disposable local qualification lanes, not persistent deployed gateways
or coordinator workers. No normal startup/reset/profile selection is changed.
P3 case preflight is explicitly synthetic in this gate and independent transport
calls are not P1-issued attempts. A cancellation receipt requests cancellation;
it does not prove stopped computation. Full current-case/action/delivery and media
integration remain later gates.

The gateway selector starts actual loopback gateway processes, acknowledges signed
input, terminates one before dispatch, and verifies fresh-process recovery under
the original receipt/operation identity. The execution selector explicitly seeds
v1 acceptance, upgrades its owned P1 profile to v2, and invokes the scripted
specialist only through newly issued P1 attempts. It verifies historical
cancellation/stale results, current useful read-only output and postcommit forced
exit/fresh read. Runtime children receive only runtime credentials; explicit
owner preparation/reconciliation/cleanup receive only owner credentials.

These additional reports live under .local/validation/p2-postgres and
.local/validation/p3-execution. The ordinary Compose profile and console still
serve their documented foundation/business paths; these gates do not deploy P2/P3
into that default UI. The [agent recovery/completion phase](../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
adds an independently owned scripted-agent worker and explicit first-result
delivery/action paths. The agent selector proves worker termination, DB-observed
claim expiry and replay while the gateway stays alive. The completion selector
explicitly prepares disposable work v3 and case v4 profiles, then verifies strict
issued results, receiver acceptance/reconciliation and one exactly confirmed fake
supplier effect. Their reports live under .local/validation/p2-postgres and
.local/validation/p3-completion.
A candidate read is not permission: P1 work v3 checks current work eligibility and
exact case confirmation atomically, then the existing leased worker performs the
fake effect outside SQL. The receiver accepts immutable bytes under a stable
identity; it proves neither playback nor human acknowledgement. Existing possible
deliveries use lookup only. All complete product/media and broader recovery gates
remain separate.

## Selected playback and process recovery gates

The [completed playback/recovery handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md)
owns selected P2-I17/P3-I14 qualification. Use ordinary local LiveKit/PostgreSQL
services and the pinned development tools; provider keys are unnecessary.

```sh
make p2-communication-check
make p2-playback-check
make p3-recovery-check
```

These commands create disposable, UUID-owned profiles. P2 communication explicitly
upgrades v6 to v7 and verifies interrupted migration, original identity, scoped
source evidence, capacity, fresh expiry, populated restore and retained I/O. The
separate playback gate runs actual scripted SDK/browser audio for normal output,
midpoint interruption and disconnect without a completion report. A compatible
Chromium installation is required; the helper accepts an explicit
--browser-executable when invoking local-setup/scripts/p2_playback_check.py directly.

P3 recovery exercises explicit original-identity lookup after specialist/coordinator
process loss through existing public P1 authorities. It does not install another
execution owner. All helpers bound children, capture, deadlines and cleanup, and
retain safe failure context. Keep actual PostgreSQL lanes serialized. They do not
change ordinary named volumes, default UI/Compose, providers or business consent.


## Current-case rehydration and standalone package checks

The [completed handoff](../docs/work-items/0038-case-rehydration-and-standalone-release.md) records implemented I18/P3-I15 interfaces and their passed
selected qualification. Default M1/P1 services, provider qualification, data and
pinned images stay unchanged. After frozen setup, local services and restricted-role
preparation, run from the repository root:

```sh
make p2-rehydration-check
make p2-rehydration-media-check
make p3-package-check
make p3-package-lab-check
```

P2 storage18 checks current native/SMS permission separately from retained history,
coherent bounded P2 sections, one allowlisted public P1 get and final fresh permission
admission. Case/history observations are non-atomic. Source fingerprints and observed
times can change while the case revision remains the same. Reading or refreshing
creates no acceptance, command, send, generation or consent. Public P1 revision 0
is displayed honestly; native input still requires its positive-revision contract.
No automatic 0-to-1 mapping or case revision is allowed.

The separate three-group scripted media gate requires the pinned managed Chromium
and actual local SFU/PG. The application closes A's real SDK/RTC owners before the
parent deletes A and proves neither A nor B exists. The fixed authenticated SMS
runs in that dormant interval; the parent then creates B. Python waits for the
exact owned B-ready marker and known original SMS result before enabling fresh mint.
B loads current case and original voice/text/SMS history before SDK readiness; only
a new accepted input generates B's reply. Old response evidence grants no current
playback, interruption, human acknowledgement or mutation authority.

P3's default package command has eight offline assertions: fresh P1 dependency wheel,
P3 wheel/sdist/rebuilt and specialist npm parity, isolated public imports/types and
installed examples. The explicit lab command repeats those eight then adds eight
actual standalone assertions, totaling sixteen rather than sixteen PG scenarios.
It needs the existing restricted PostgreSQL roles and a sole local gate slot. It
uses a local specialist and receiver, separately supplied exact synthetic consent,
one leased fake effect, owned consumer loss and fresh original replay. Owner/worker
instrumentation remains test-only; there is no P2 gateway, SFU or provider requirement.

The selected 18-group storage gate passed in 6.534 seconds, the three-group media gate in 35.797 seconds and P3 combined 16-case gate
in 58.885 seconds, with exact source/archive inventories and actual owned cleanup.
Isolated P2 Python consumption passed 111 tests over nine payloads in 15 commands
(52.364 seconds); the npm consumer passed seven stages in 2.1696 seconds. The 166
P2 compatibility assertions passed in 98.997 seconds. These are observations of the
selected synthetic local runs, not latency or capacity guarantees.

The closure checks passed 2148 Python and 1224 TypeScript tests (503 console, 632 P2,
89 P3), broad/strict typing of 144/132 files, formatting of 387 files, 113 documentation
checks and 29 Mermaid syntax checks. Ordinary doctor/smoke preserved ten audio frames and original M1
state. Full P2/P3 charter registration remains planned; these selected gates do not
complete all seventeen P2 or fourteen P3 acceptance rows.
Retain unresolved child/bridge/read owners and private work for explicit cleanup;
reaping children precedes schema deletion, and bridge settlement precedes reader
closure. Failed attempts remain failed. These commands perform no remote CI or
provider inference and do not complete full P2/P3 charter registration.

## Optional operations and fixed-policy setup

Use the [operations and policy handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
and [P2 operations guide](../projects/channel-continuity/OPERATIONS.md).
The default Compose topology and console remain unchanged. The operations page
uses its own Vite/build entry and an explicitly configured loopback read server;
PostgreSQL remains the existing local restricted-role service. No second database,
queue, image, public carrier or provider credentials are required.

```sh
make p2-operations-plan
make p2-operations-build
make p2-operations-check
make p3-fixed-policy-plan
make p3-fixed-policy-check
make p3-fixed-policy-package-check
```

The P2 gate accepts --browser-executable through its Python helper for a prepared
Chromium installation. Serialize its PostgreSQL lane with the existing durable
and media gates. The page uses a scoped operator token and persistent private
cursor key configured by its host; the browser receives no mutation credential.
Set only the documented variables in the project guide. The app's declared P2
workspace dependency is installed with the frozen lock; its optional build
compiles the public P2 package first. Default console compilation excludes that
optional graph, preserving the existing standalone console Docker build boundary.

P3 fixed-policy gates require the pinned local Python/Node tools and installed
build dependencies, but no PostgreSQL, SFU, external models or .env.providers.
They create finite loopback services and private source/installed consumers.
Version 2 is explicitly selected and standalone; version 1 defaults and the
durable P3 runner remain unchanged. No image or policy content grants tools or
confirmation. Failed normal attempts remain non-passing and retain safe evidence;
remove owned state only after actual dependent processes/readers settle.

Selected 0040 qualification passed for the optional operations profile and the
standalone fixed-policy API. The completed handoff records exact source, installed,
media-compatibility and cleanup scope. Existing default doctor/smoke passed eight
checks and ten diagnostic audio frames with original M1 preserved. Selected
P2-I21/P3-I18A qualification subsequently passed in 0041. Selected P3-I18B
native RTC text qualification passed in 0042.
Integrated voice/text/SMS return routing, live-provider behavior and the requested final demo video follow their
separate gates; a build or healthy service alone cannot qualify them.

## Joined channel-policy setup

The active [joined work item](../docs/work-items/0045-joined-native-channel-policy.md)
adds an explicit owner setup tool for three fresh isolated schemas and private
configuration. Its inert plan can be inspected from the repository root:

```sh
make channel-policy-setup-plan
make channel-policy-python-plan
```

The owner tool uses the existing local infrastructure settings. Provider keys are
outside this setup path. Runtime configuration contains no migration credential;
Node receives its separate role environment. The prepared profile preserves real
case/task/receiver identities, a stable app owner and supported synthetic evidence.
An existing target directory is rejected. Partial failures retain private journals;
normal serving and stop never reinstall or reset state.

Actual fresh-schema setup now succeeds, with separate read-only version,
receiver, case and original-M1 checks. Future preparations also publish the
nonsecret specialist configuration after validating shared evidence identities.
A preliminary signed-SMS/execution/delivery path and scoped normal restarts are
observed in the work item; they do not complete the final frozen integration gate.
The room-bound current-result transport and Parent components are implemented;
their connected media and provider qualification remain pending. Plan commands
create no database, room, model or carrier call.

The explicit scripted launcher consumes an already prepared private profile and
prebuilt gateway, specialist and joined UI. It runs no build, install, migration,
reset, sender association or provider loader. Inspect its inert plan first:

```sh
make channel-policy-launch-plan
```

Its CLI is `serve --profile ABSOLUTE_OWNER_CONFIG --node ABSOLUTE_NODE_EXECUTABLE`;
add `--no-ui` for the backend-only process composition. Actual joined startup and
media qualification are still pending; a successful plan is not runtime readiness.
The optional UI uses the prebuilt public Vite preview at
http://127.0.0.1:5179/channel-policy.html. The launcher prints only the private
operator-key file path; enter that key explicitly into the page. Keys remain out
of URLs, browser storage, child arguments and diagnostics.

Normal SIGINT/SIGTERM starts UI and Parent cleanup independently, drains both
before gateway/specialist dependencies, and preserves all product data. The
private operator key and fixed bridge configuration survive normal restart. Only
the exact original active marker is removed after owned work settles. Unresolved
cleanup retains the original owners and marker; another signal retries the same
cleanup. An existing active marker fails closed, with no automatic crash recovery
or destructive repair.
