# Agent Continuity Lab

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Onboard engineers to P1: what is implemented, where authority lives and which commands work |
| Audience | Engineers who build, run or validate P1; coding agents |
| Scope | P1 capability status, requirements, commands and validation; excludes acceptance definitions and design detail |
| Owns | P1 product onboarding: capability summary, requirements and working commands |
| Related | [V1 charter](../../docs/projects/agent-continuity-scope.md) · [Project design](Design.md) · [Project instructions](AGENTS.md) · [Standalone distribution guide](python/README.md) |

## Overview

P1, Agent Continuity Lab, builds a Python durable-operation API for business work
that outlives a realtime session. This README is for engineers who build, run or
validate P1. It summarizes what is implemented, links the authoritative documents
and lists the working commands. The
[V1 charter](../../docs/projects/agent-continuity-scope.md) defines behavior and
the stable P1 acceptance IDs.

Contents:

- [Implementation status](#implementation-status): qualification, the standalone
  package, the booking case authority, the opt-in work profile, inference profiles
  and the Phase G native conversation.
- [Documentation](#documentation) and [Requirements](#requirements).
- [Commands](#commands): fast checks, the Phase A example, the PostgreSQL lane,
  schema upgrades and the persistent business workspace.
- [Validation](#validation) and [Next milestone](#next-milestone).

### Terms used in this README

| Term | Meaning |
| --- | --- |
| M1 | The original SQLite confirmed-investigation intake, kept on the ordinary browser and API path |
| Phases A to H | Implementation phases in the [P1 implementation plan](../../docs/implementation/p1-agent-continuity.md). H1 is the inquiry workload slice of Phase H; H2 is its restart, slow-dependency, saturation and shutdown slice |
| Task IDs | Plan work items such as P1-I26. They are not acceptance IDs such as P1-20 |
| PostgreSQL v1 to v5 | The booking case-authority schema versions. Each upgrade is an explicit owner-only step. Runtime surfaces that require ACTIVE v4 also accept ACTIVE v5 |
| Work profile v1 to v4 | The separate opt-in schema line behind `work_api`, used by P3 delegation |
| Inference profiles | scripted (default), local_real and provider_real |
| ACK | Acknowledgement |
| POC | Proof of concept |

## Implementation status

P1 V1 is implemented and locally qualified with the explicitly selected
provider_real v2 profile. All twenty P1 acceptance rows have retained passing
reports and an independently verified index. The
[release work item](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
records the exact scope, source-bound evidence and limits. Complete P2 and P3
acceptance remains pending.

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1, all twenty acceptance rows | Qualified | provider_real v2 run in the [release work item](../../docs/work-items/0019-p1-phase-h-release-qualification.md) |
| Requalification after the v5 storage change | Partial: P1-20 open | 20 of 21 rows passed in the [0047 work item](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| [Standalone Python package](#standalone-package) | Qualified | P1-I26 checkpoint in the [standalone distribution guide](python/README.md) |
| [PostgreSQL v4 booking authority](#booking-case-authority), workers and outbox | Qualified | Runtime gates in the [release work item](../../docs/work-items/0019-p1-phase-h-release-qualification.md) |
| Booking v5 retry pacing | Implemented | Owner-only v5 upgrade in the [0047 work item](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| [Work profile](#opt-in-work-profile-for-p3) v1: accepted work | Qualified | Selected gate in the [acceptance phase](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| Work profile v2: issued execution | Qualified | Selected gate in the [issued-execution phase](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| Work profile v3: delivery and guarded action | Qualified | Selected gates in the [completion phase](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| Work profile v4: result feed | Qualified | Selected qualification in the [phase handoff](../../docs/work-items/0032-linked-confirmation-and-result-projections.md) |
| scripted [inference profile](#inference-profiles) | Implemented | The default regression profile and lane |
| local_real inference profile | Not qualified | Unqualified under its original limits; [local-real guide](../../docs/local-real-inference.md) |
| provider_real v2 inference profile, selected | Qualified | Deepgram nova-3, OpenAI gpt-5.4-mini and ElevenLabs eleven_v4_turbo; two-case actual browser gate passed with cleanup |
| [Phase G native conversation](#native-conversation-and-business-workspace), scripted local media | Qualified | Local combined gate in the [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| Physical microphone quality and human hearing | Not qualified | [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) |

After the v5 storage change, the
[0047 requalification](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)
passed 20 of 21 provider_real deep-gate rows: BASE-01 and P1-01 to P1-19, with
104 tests and zero skips. Its P1-20 run stayed blocked on that network. The
passing reference run had mounted an approved certificate authority (CA) bundle
into the native container. The 0047 runs used the image trust store and recorded
zero speech-to-text (STT), language-model (LLM) and text-to-speech (TTS) usage
before the agent's reply timed out.

### Standalone package

The standalone Python 3.14 distribution exposes typed synchronous and asynchronous
APIs, installed examples and isolated host and Linux consumers. The canonical
source remains `projects/agent-continuity/python/src/continuity_lab`. Services
consume the locked package without checkout injection, that is, without adding the
repository checkout to the import path.

### Booking case authority

The SQLite M1 investigation contract and its original identities remain preserved.
The PostgreSQL v4 path adds:

- exact quote and revision confirmation;
- durable waits, retries and deadlines;
- cancellation intent and supplier-effect reconciliation;
- completion outbox delivery;
- server-time leases and bounded pull workers.

The owner-only v5 upgrade adds a persisted retry due time for mutation effects that
fail with `dependency_unavailable` before dispatch. On v5 such an effect waits until
its due time: 1 s, doubling to 30 s, never past the deadline. Cancellation is never
held behind it, and v4 keeps immediate retry.

Supplier cooperation or explicit uncertainty governs external effects. A database
lease epoch alone cannot fence a remote call. Current runtime gates prove that
accepted work survives conversation End and declared worker and API faults, with
independent supplier and receiver truth.

### Opt-in work profile for P3

The additive, opt-in `work_api`/`work_admin` profile owns immutable read-only
accepted delegation bytes and scoped find, get and requested cancellation. It keeps
no P3 side ledger. Version 1 is acceptance only. Each later version is an explicit
owner-only upgrade.

| Version | Adds | Public surfaces |
| --- | --- | --- |
| 1 | Immutable read-only accepted delegation bytes; scoped find, get and requested cancellation | `work_api`, `work_admin` |
| 2 | Scoped P1-issued read-only attempts and immutable result observations | `execution_api` |
| 3 | Immutable result-delivery intent, possible-call and receipt records, plus guarded case-action receipts | `delivery_api`, `receiver_api`, `action_api`, `case_control_api` |
| 4 | A result feed: a stable source UUID, contiguous scoped committed result references and source- and scope-bound cursors | `result_feed_api` |

These rules hold across the versions:

- The version-3 surfaces keep result observations, receiver acceptance and
  independent exact human confirmation separate.
- The guarded action uses one transaction across the work profile and the existing
  booking v4 profile. Neither specialists nor accepted results grant themselves
  consent.
- In version 4, historical adoption is labelled `adopted_history`. Live result and
  event commits share the existing admission transaction.
- P1 parses no P3 result semantics and grants no projection authority to execute or
  confirm.
- No profile adds an autonomous scheduler or message-sending transport.

Each phase records its own evidence:

- The [acceptance phase](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)
  and the
  [issued-execution phase](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
  distinguish their qualification boundaries.
- The [completion phase](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
  records the version-3 delivery and guarded-action tests and their remaining
  limits.
- The [phase handoff](../../docs/work-items/0032-linked-confirmation-and-result-projections.md)
  records passing selected qualification for the version-4 slice. Existing booking,
  native and provider behavior and complete P1 release evidence retain their
  original scope.

### Inference profiles

Native consumers accept trusted scripted, local_real or provider_real composition.
None of them changes durable P1 authority or exact human confirmation. Both
real-profile implementations are present; the capability table above gives each
profile's status.

P1 V1 is qualified for the local POC using provider_real v2. A provider pass cannot
qualify the separately declared local engine profile. The
[local-real guide](../../docs/local-real-inference.md) owns local engines. The
[provider guide](../../docs/provider-demo.md) owns the Deepgram, OpenAI and
ElevenLabs opt-in and the private keys.

### Native conversation and business workspace

Phase G implements a genuine native AgentSession consumer of the current durable
service:

- No-argument submit, get and cancel tools use a signed, frozen investigation
  binding. Exact quote approval remains a separate authenticated UI action.
- Current scoped projections show request, attempt, wait, effect, outcome and
  delivery, with bounded history and honest unknown and reconnect behavior.
- Local scripted speech sends actual WebRTC audio from an explicitly selected
  bundled WAV file through WebAudio, without model or carrier credentials.
- The public RoomIO readiness barrier precedes speech and controls.
  `session_host=False` removes alternate, unbound SDK ingress.
- Explicit End retires the room, and a fresh consumer resumes the same durable case.

Physical microphone quality and human hearing remain unqualified. Selected
provider_real v2 inference has separate passing Phase H evidence. The completed
Phase H release separately qualifies artifacts, workloads and selected provider
inference; scripted media alone supplies no such claim. Read the
[conversation guide](../../docs/conversation-and-showcase.md) and the
[Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
for local commands, tests and the current combined gate.

## Documentation

The table lists project documents first, then operations guides, then validation
and version references.

| Document | Purpose |
| --- | --- |
| [Project instructions](AGENTS.md) | Agent workflow, P1 development rules and verification |
| [Project design](Design.md) | P1 implementation boundaries, state ownership and failure handling |
| [V1 scope and acceptance matrix](../../docs/projects/agent-continuity-scope.md) | Required behavior and the stable P1 acceptance IDs; authoritative for scope |
| [Shared architecture](../../Design.md) | Shared data flow, state authority, interfaces and failure boundaries |
| [Granular implementation plan](../../docs/implementation/p1-agent-continuity.md) | Phase gates, task prerequisites and failure evidence |
| [Standalone distribution guide](python/README.md) | The package's typed public imports, extras, installed commands and isolated artifact gate |
| [Case and continuation guide](../../docs/case-and-continuation.md) | Case authority, wait and retry operations |
| [Effects and completion guide](../../docs/effects-and-completion.md) | Mutation, cancellation, target binding and outbox operations |
| [Leases and worker operations](../../docs/leases-and-workers.md) | Scope and schema selection, provider identities, lease expiry, capacity and bounded shutdown |
| [Local stack setup](../../local-setup/README.md) | Host requirements and lifecycle commands |
| [Local console](../../apps/local-console/README.md) | TypeScript operator console and browser lifecycle |
| [Validation plan](../../docs/validation-plan.md) | Separate deterministic correctness, actual local media and real-model evidence |
| [Technology baseline](../../docs/technology-baseline.md) | Selected versions and validation boundaries |
| [Harness guide](../../harness/README.md) | Harness commands and outcome semantics |

The granular plan's task IDs are not product acceptance IDs; the charter remains
authoritative. The root application consumes the standalone package as a
workspace member. No root `continuity_lab` source shadow exists.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python runtime | The pinned root runtime, Python 3.14 | Use it before running the full fast suite |
| Python dependencies | Frozen `uv.lock` with all declared extras and development dependencies | The first command under [Commands](#commands) installs them |
| Test dependencies | The same frozen environment | Service, Agents SDK and inference-boundary tests require it; the pure intake subset remains standard-library-only |
| Inference credentials | None | Only the explicit provider_real opt-in in the [provider guide](../../docs/provider-demo.md) uses provider keys |
| Docker and Compose | Compose 2+ | Runs the shared lab with pinned images; the [local setup guide](../../local-setup/README.md) has host requirements and lifecycle commands |
| Selected versions | [Technology baseline](../../docs/technology-baseline.md) | Records selected versions and validation boundaries |

## Commands

Run every command from the repository root. The table indexes the tasks; the
subsections keep each runnable sequence.

| Task | Command | Notes |
| --- | --- | --- |
| Install frozen dependencies | `uv sync --frozen --all-extras --dev` | All declared extras and development dependencies |
| Run the existing M1 demo | `.venv/bin/python -m continuity_lab demo` | Disposable synthetic state |
| Run one acceptance runner | `.venv/bin/python -m harness run P1-01` | The first block lists BASE-01 and P1-01 to P1-05 |
| List the P1 runners | `.venv/bin/python -m harness list --project p1` | Registered P1 runners |
| Run the P1 fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1` | Root and standalone package Python suites |
| Run every P1 runner | `.venv/bin/python -m harness run --project p1` | P1-20 defaults to the unqualified local_real profile |
| Try the Phase A SQLite example | `.venv/bin/python -m continuity_lab.execution_cli` | `migrate`, `submit` and `list` against `.local/p1-demo`; accepts and inspects work only |
| Run the independent inquiry worker | The `PYDEMO` script below | Initializes a separate supplier fixture, then runs `continuity_lab.inquiry_worker` |
| Demonstrate a controlled crash | `.venv/bin/python -m harness run P1-05` | Isolated state and owned processes |
| Run the PostgreSQL lane | `make postgres-check` | After `init`, `start`, `prepare-postgres` and `migrate-postgres` |
| Run the phase demos | `make phase-d-demo`, `make phase-e-demo`, `make phase-f-demo` | Listed after the PostgreSQL lane setup in the same block |
| Upgrade an ACTIVE application schema | `upgrade-postgres`, `upgrade-effects`, `upgrade-coordination`, `upgrade-retry-pacing` | Owner-only `local-setup/stack.py` commands, applied in order |
| Prepare the persistent business workspace | `.venv/bin/python local-setup/stack.py prepare-business` | After `init`, `start` and `prepare-postgres` |
| Start workers | `init-worker-fixtures`, then `start-workers` or `start-business` | Through `local-setup/stack.py` |
| Inspect or stop workers | `worker-status`, `stop-workers` | Through `local-setup/stack.py`; the `p1-workers` profile retains `worker_data` |

### Fast checks and acceptance runners

Run from the repository root:

```sh
uv sync --frozen --all-extras --dev
.venv/bin/python -m continuity_lab demo
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P1-01
.venv/bin/python -m harness run P1-02
.venv/bin/python -m harness run P1-03
.venv/bin/python -m harness run P1-04
.venv/bin/python -m harness run P1-05
.venv/bin/python -m harness list --project p1
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1
.venv/bin/python -m harness run --project p1
```

All twenty P1 rows have registered runners and retained passing evidence.

- The final command, `harness run --project p1`, executes the required service,
  browser and live lanes. It still defaults to the unqualified local_real profile
  for P1-20.
- To reproduce the qualified provider_real v2 scope, follow the explicit opt-in and
  prerequisites in the [provider guide](../../docs/provider-demo.md). No paid
  inference runs implicitly.
- A structural pass alone does not qualify product behavior.
- The fast lane (`scripts/harness-check.sh`) runs both the root and the standalone
  package Python suites, even when structural checks focus on P1.
- The standalone Python README retains its artifact-qualified P1-I26 checkpoint.
  The [current Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
  owns later release status.

### Phase A SQLite inquiry example

For a disposable Phase A example, create `.local/p1-demo` first, then run:

```sh
mkdir -p .local/p1-demo
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 migrate --backup .local/p1-demo/before-v1.sqlite3
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 submit --scope demo-traveller --key inquiry-001 --booking DEMO-BK-001 --check-in 2030-12-10 --confirm
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 list --scope demo-traveller
```

- Only the migrate command creates schema. Existing stores must be quiesced and
  backed up first, and backups are not overwritten. A repeated v1 migration
  verifies the schema.
- The Phase A commands only accept and inspect work.
- The execution CLI emits safe JSON results and logs. Its fixed input and exception
  codes do not serialize raw dependency messages.
- The legacy M1 CLI and API remain separate and cannot perform a booking mutation.

For a normal independent worker, initialize a separate supplier fixture, then run
`inquiry_worker` with the task ID returned by submit. This reproducible example
performs those steps:

```sh
.venv/bin/python - <<'PYDEMO'
import json, subprocess, sys
from pathlib import Path
from continuity_lab.execution import ExecutionStore
from continuity_lab.supplier import FakeSupplier, initialize_supplier
folder = Path(".local/p1-demo")
database, supplier_db = folder / "inquiry.sqlite3", folder / "supplier.sqlite3"
initialize_supplier(supplier_db, scope_id="demo-traveller")
store, supplier = ExecutionStore(database), FakeSupplier(supplier_db)
record = store.list(scope_id="demo-traveller")[0]
before = supplier.booking(scope_id=record.scope_id, booking_reference=record.request.booking_reference)
subprocess.run([sys.executable, "-m", "continuity_lab.inquiry_worker", "--db", str(database), "--supplier-db", str(supplier_db), "--scope", record.scope_id, "--task-id", record.task_id], check=True)
after = supplier.booking(scope_id=record.scope_id, booking_reference=record.request.booking_reference)
assert before == after
print(json.dumps({"booking_unchanged": before == after, "logical_inquiries": supplier.count_inquiries(scope_id=record.scope_id)}))
PYDEMO
```

### Controlled crash demonstration

P1-05 (`harness run P1-05` above) is the one-command controlled crash
demonstration. It creates isolated state and owned processes and inspects both
stores. It does not terminate an arbitrary service or expose process controls
through the UI.

### PostgreSQL lane and phase demos

For the explicit PostgreSQL lane, preserve the existing stack and run:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
make postgres-check
make phase-d-demo
make phase-e-demo
make phase-f-demo
```

The Phase E demo owns an isolated schema and independent persisted supplier and
receiver files. It runs this recovery sequence:

1. Stop runtime-only containers after supplier and receiver success, before local
   acknowledgement.
2. Recover the same effect and event.
3. Verify the exact booking revision and one logical receiver receipt.

It also checks pre-dispatch cancellation. The Phase E runner does not enable the
browser business profile. Use the separately managed Phase G conversation and
showcase path for those tools.

### Upgrading an existing ACTIVE application schema

For a deliberately selected ACTIVE application schema, apply v2, v3, v4 and v5 in
order:

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
.venv/bin/python local-setup/stack.py upgrade-coordination
.venv/bin/python local-setup/stack.py upgrade-retry-pacing
```

| Task | Command | Notes |
| --- | --- | --- |
| Upgrade ACTIVE v1 to v2 | `upgrade-postgres` | Owner-only |
| Upgrade ACTIVE v2 to v3 | `upgrade-effects` | Owner-only |
| Upgrade ACTIVE v3 to v4 | `upgrade-coordination` | Owner-only; an unmanaged running v3 inquiry must reconcile first |
| Upgrade ACTIVE v4 to v5 | `upgrade-retry-pacing` | Owner-only |

- The initial `migrate-postgres` command (`postgres_cli schema`) leaves a new target
  in STAGING. The upgrade commands operate only on an already ACTIVE target.
- The real PostgreSQL gate creates isolated synthetic schemas and tests the complete
  cutover protocol and worker recovery. It does not cut over the live M1 API
  database. Missing setup is a failure.
- Read the [cutover decision](../../docs/decisions/0003-postgres-cutover-and-scope.md)
  for checkpoint recovery, backup safety and credential ownership.

Credentials are separated by role:

| Commands | Read credentials from |
| --- | --- |
| Owner-only `postgres_cli` schema, cutover, upgrade, upgrade-effects, upgrade-coordination and upgrade-retry-pacing | `P1_MIGRATION_*` |
| Runtime status, submit, get, list, history and work | `P1_POSTGRES_*` |

Configure these from the private local settings without printing or sourcing
secrets. Never pass a password in argv.

### Persistent business workspace and workers

For a fresh persistent workspace, follow the explicit
[business preparation](../../local-setup/README.md#first-persistent-p1-business-workspace):

1. Run the ordinary `init`, `start` and `prepare-postgres` commands.
2. Run `.venv/bin/python local-setup/stack.py prepare-business`.
3. Run `init-worker-fixtures`, then `start-workers` or `start-business`.

Behavior to expect:

- The helper uses its own empty auxiliary source and private retained backups. It
  never quiesces the live M1 database. Its ordered upgrades include the additive v5
  step ([0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)).
- `migrate-postgres` and the isolated demos alone do not activate this persistent
  target.
- Existing application schemas retain their controlled cutover history and ordered
  upgrades.
- Use `worker-status` and `stop-workers` through `local-setup/stack.py`. The
  `p1-workers` profile retains `worker_data`.
- Normal stop and start preserve fixtures, original IDs, waits, effects and
  delivery.
- Startup never performs an implicit migration or fabricates confirmation.

Read the [worker guide](../../docs/leases-and-workers.md) for scope and schema
selection, provider identities, database lease expiry, capacity and bounded
shutdown.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| P1 fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1` | Root and standalone package Python suites; a structural pass alone does not qualify product behavior | Implemented |
| P1 acceptance runners | `.venv/bin/python -m harness run --project p1` | Required service, browser and live lanes for the P1 rows; P1-20 defaults to unqualified local_real | Qualified with provider_real v2 |
| Real PostgreSQL gate | `make postgres-check` | Complete cutover protocol and worker recovery on isolated synthetic schemas | Qualified; passed after v5 in [0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| Phase E recovery demo | `make phase-e-demo` | Same effect and event recovery after a stop before local acknowledgement, plus pre-dispatch cancellation | Qualified in the [Phase E work item](../../docs/work-items/0011-p1-phase-e-effects-and-completion.md) |
| Phase F worker demo | `make phase-f-demo` | Leased worker, restart and shutdown evidence without resetting retained state | Qualified: final gate in the [Phase F work item](../../docs/work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Local stack readiness and transport smoke | See the [local setup guide](../../local-setup/README.md) | Actual diagnostic text and audio; not configured STT, LLM or TTS quality or the product V1 release | Implemented |
| Phase G media gate | See the [conversation guide](../../docs/conversation-and-showcase.md) | Scripted local providers with real browser and native audio | Qualified: local combined gate in the [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| provider_real v2 P1-20 gate | See the [provider guide](../../docs/provider-demo.md) | Both actual browser cases with cleanup | Qualified; rerun after v5 open |
| local_real and physical microphone quality | Not applicable | No current gate establishes either | Not qualified |

### Evidence levels

The [V1 acceptance matrix](../../docs/projects/agent-continuity-scope.md) defines
required scenarios. The [shared validation plan](../../docs/validation-plan.md)
separates deterministic correctness, actual local media and real-model evidence.

- Local-ready V1 requires the designated local checks.
- Portfolio-ready V1 adds the required real-model runs, review, benchmark evidence
  and demonstration.

Harness reports live under the ignored `.local/harness` directory.

### Local stack and media checks

- The shared local stack's readiness and transport smoke checks are separate, and
  its volumes persist. Normal stop and start preserve current local state. Use the
  documented explicit reset only when you intend to remove synthetic data.
- The Phase G gate is separate from the local stack checks. P1 V1 is qualified for
  the local POC using provider_real v2.

## Next milestone

The P1 V1 scope is complete for the local POC. Remaining P1 work:

| Step | Outcome | Gate |
| --- | --- | --- |
| Maintain the completed P1 scope | The scope keeps its source-bound evidence | Source-bound acceptance, artifact and runtime gates |
| Rerun P1-20 with `P1_PROVIDER_CA_BUNDLE` pointing at the owner's approved bundle | Closes the open P1-20 requalification finding | P1-20 provider_real deep-gate row |
| Preserve historical H1 and phase evidence | No historical evidence is relabelled as a new measurement | Not applicable |
| Qualify the local engine profile in future | local_real gains its own qualification | Its own declared run; provider evidence cannot qualify it |

The [0047 work item](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)
records the P1-20 rerun as open, along with its other open findings.

P2 and P3 remain partially implemented. They use P1 only through its documented
public ports and installed package. The [build plan](../../docs/build-plan.md) owns
their frontiers.
