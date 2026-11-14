# Agent Continuity Lab

Status: Active
Last reviewed: 11 November 2026

## Overview

Build a Python durable-operation API for business work that outlives a realtime session.
The V1 charter defines behavior and stable P1 acceptance IDs.

## Implementation status

P1 V1 is implemented and locally qualified with the explicit provider_real v2
profile. All twenty P1 acceptance rows have retained passing reports and an
independently verified index. The standalone Python 3.14 distribution exposes
typed sync/async APIs, installed examples and isolated host/Linux consumers.
Canonical source remains projects/agent-continuity/python/src/continuity_lab;
services consume the locked package without checkout injection.

The additive opt-in work_api/work_admin profile now owns immutable read-only
accepted delegation bytes and scoped find/get/requested-cancel, with no P3 side
ledger. Version 1 is acceptance only; the explicit owner-only version-2 upgrade
adds scoped P1-issued read-only attempts and immutable result observations through
execution_api. The explicit version-3 upgrade adds immutable result-delivery intent,
possible-call and receipt records plus guarded case-action receipts. The new
public delivery_api/receiver_api/action_api/case_control_api surfaces keep result
observations, receiver acceptance and independent exact human confirmation separate.
The guarded action uses one transaction across the work and existing booking v4
profiles; neither specialists nor accepted results grant themselves consent. No
profile adds an autonomous scheduler or message-sending transport. The [acceptance phase](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)
and [issued-execution phase](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
distinguish their qualification boundaries. The [completion phase](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
records the v3 delivery and guarded-action tests and their remaining limits.
Explicit work v4 now adds result_feed_api: a stable source UUID, contiguous
scoped committed result references and source/scope-bound cursors. Historical
adoption is labelled adopted_history; live result/event commits share the existing
admission transaction. P1 parses no P3 result semantics and grants no projection
authority to execute or confirm. The
[phase handoff](../../docs/work-items/0032-linked-confirmation-and-result-projections.md)
records passing selected qualification; existing booking/native/provider
behavior and complete P1 release evidence retain their original scope.

The SQLite M1 investigation contract and original identities remain preserved.
The PostgreSQL v4 path adds exact quote/revision confirmation, durable waits,
retries/deadlines, cancellation intent, supplier-effect reconciliation, completion
outbox delivery, server-time leases and bounded pull workers. Supplier cooperation
or explicit uncertainty governs external effects; a database epoch alone cannot
fence a remote call. Current runtime gates prove accepted work survives conversation
End and declared worker/API faults, with independent supplier/receiver truth.

Scripted is the default regression profile. Selected provider_real v2 uses
Deepgram nova-3, OpenAI gpt-5.4-mini and ElevenLabs eleven_v4_turbo; the two-case
actual browser gate passed. The separate local_real implementation remains
unqualified under its original limits. Read the
[release work item](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
for exact scope, source-bound evidence and limits; complete P2/P3 acceptance remains pending.

## Documentation

- [Project instructions](AGENTS.md)
- [Project design](Design.md)
- [V1 scope and acceptance matrix](../../docs/projects/agent-continuity-scope.md)
- [Shared architecture](../../Design.md)
- [Validation plan](../../docs/validation-plan.md)
- [Technology baseline](../../docs/technology-baseline.md)
- [Case and continuation guide](../../docs/case-and-continuation.md)
- [Effects and completion guide](../../docs/effects-and-completion.md)
- [Leases and worker operations](../../docs/leases-and-workers.md)
- [Harness guide](../../harness/README.md)
- [Local stack setup](../../local-setup/README.md)
- [Local console](../../apps/local-console/README.md)

Read the [granular implementation plan](../../docs/implementation/p1-agent-continuity.md)
for phase gates, task prerequisites and failure evidence. These task IDs are not
product acceptance IDs; the charter remains authoritative.

The [standalone distribution guide](python/README.md) owns its typed public
imports, extras, installed commands and isolated artifact gate. The root application
consumes this workspace member; no root continuity_lab source shadow exists.

## Requirements

Use the pinned root Python runtime and frozen uv.lock with all declared extras and development dependencies before the full fast suite. Service, Agents SDK and inference-boundary tests require those dependencies; the pure intake subset remains standard-library-only. No
external inference credentials are needed. Docker and Compose 2+ run the shared
lab with pinned images; see the [local setup guide](../../local-setup/README.md)
for host requirements and lifecycle commands. The
[technology baseline](../../docs/technology-baseline.md) records selected versions
and validation boundaries.

## Commands

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

All twenty P1 rows now have registered runners and retained passing evidence.
The final command executes required service/browser/live lanes and still defaults
to the unqualified local_real profile for P1-20. To reproduce the qualified
provider_real v2 scope, follow the explicit opt-in and prerequisites in the
[provider guide](../../docs/provider-demo.md); no paid inference runs implicitly.
A structural pass alone does not qualify product behavior. The fast lane runs both
root and standalone package Python suites even when structural checks focus on P1.
The standalone Python README retains its artifact-qualified I26 checkpoint; the
[current Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
owns later release status.

For a disposable Phase A example, first create .local/p1-demo, then run:

```sh
mkdir -p .local/p1-demo
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 migrate --backup .local/p1-demo/before-v1.sqlite3
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 submit --scope demo-traveller --key inquiry-001 --booking DEMO-BK-001 --check-in 2030-12-10 --confirm
.venv/bin/python -m continuity_lab.execution_cli --db .local/p1-demo/inquiry.sqlite3 list --scope demo-traveller
```

Only the migration command creates schema. Existing stores must be quiesced and
backed up; backups are not overwritten. A repeated v1 migration verifies schema.
The legacy M1 CLI/API remains separate and cannot perform a booking mutation.
The new CLI emits safe JSON results/logs; its fixed input/exception codes do not
serialize raw dependency messages. The Phase A commands only accept/inspect. For a normal independent worker,
initialize a separate supplier fixture, then run inquiry_worker with the task ID
returned by submit. The following reproducible example performs those steps:

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

P1-05 is the one-command controlled crash demonstration. It creates isolated
state and owned processes and inspects both stores; it does not terminate an
arbitrary service or expose process controls through the UI.

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

The Phase E demo owns an isolated schema and independent persisted supplier/
receiver files. It stops runtime-only containers after supplier/receiver success
before local acknowledgement, recovers the same effect/event, and verifies exact
booking revision and one logical receiver receipt. It also checks pre-dispatch
cancellation. That Phase E runner does not enable the browser business profile;
use the separately managed G conversation/showcase path for those tools.

For a deliberately selected ACTIVE application schema, apply v2, v3 and v4 in order:

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
.venv/bin/python local-setup/stack.py upgrade-coordination
.venv/bin/python local-setup/stack.py upgrade-retry-pacing
```

The initial migrate-postgres/schema command leaves a new target STAGING; the
upgrade commands operate only on an already ACTIVE target. The real PostgreSQL gate
creates isolated synthetic schemas and tests the complete cutover protocol and
worker recovery; it does not cut over the live M1 API database. Missing setup is
a failure. Read the [cutover decision](../../docs/decisions/0003-postgres-cutover-and-scope.md)
for checkpoint recovery, backup safety and credential ownership. Owner-only
postgres_cli schema/cutover/upgrade/upgrade-effects/upgrade-coordination/upgrade-retry-pacing commands read P1_MIGRATION_*; runtime status/submit/
get/list/history/work commands read P1_POSTGRES_*. Configure these from the private
local settings without printing/sourcing secrets. Never pass a password in argv.

For a fresh persistent workspace, follow the explicit
[business preparation](../../local-setup/README.md#first-persistent-p1-business-workspace):
run .venv/bin/python local-setup/stack.py prepare-business after ordinary
init/start/prepare-postgres, then init-worker-fixtures and start-workers or
start-business. The helper uses its own empty auxiliary source and private
retained backups; it never quiesces the live M1 database. migrate-postgres and the
isolated demos alone do not activate this persistent target. Existing application
schemas retain their controlled cutover history and ordered upgrades.
Use worker-status and stop-workers through local-setup/stack.py. The p1-workers profile retains
worker_data. Normal stop/start preserves fixtures, original IDs, waits, effects
and delivery. An unmanaged running v3 inquiry must reconcile before v4 upgrade.
Read the worker guide for scope/schema selection, provider identities, DB lease
expiry, capacity and bounded shutdown. Startup never performs an implicit
migration or fabricates confirmation.

### Explicit inference profiles

Native consumers accept trusted scripted, local_real or provider_real composition;
none changes durable P1 authority or exact human confirmation. Scripted remains
the default regression lane. The [local-real guide](../../docs/local-real-inference.md)
owns local engines; the [provider guide](../../docs/provider-demo.md) owns the
Deepgram/OpenAI/ElevenLabs opt-in and private keys. Both real-profile implementations are present. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified.
A provider pass cannot qualify the separately declared local engine profile.

## Validation

The [V1 acceptance matrix](../../docs/projects/agent-continuity-scope.md) defines required scenarios.
The [shared validation plan](../../docs/validation-plan.md) separates deterministic
correctness, actual local media and real-model evidence. Local-ready V1 requires
the designated local checks; portfolio-ready V1 adds the required real-model runs,
review, benchmark evidence and demonstration. Harness reports live under ignored .local/harness. The shared local stack has
separate readiness/transport smoke checks and persistent volumes. Its actual
diagnostic text/audio checks do not prove configured STT/LLM/TTS quality or product
V1 release. The separate G gate exercises scripted local providers and real
browser/native audio. Physical microphone quality and local_real remain unqualified. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. Normal
stop/start preserves current local state; use the documented explicit reset only
when synthetic data removal is intended.

## Next milestone

Maintain the completed P1 scope and its source-bound acceptance/artifact/runtime
gates. Preserve historical H1/phase evidence without relabelling it as a new
measurement. P2/P3 remain partially implemented and use P1 only through its documented public
ports and installed package. The [build plan](../../docs/build-plan.md) owns their
frontiers. A future local-engine qualification requires its own declared run;
provider evidence cannot qualify it.

## Native conversation and business workspace

Phase G implements a genuine native AgentSession consumer of the current durable
service: no-argument submit/get/cancel tools use a signed frozen investigation
binding, while exact quote approval remains a separate authenticated UI action.
Current scoped projections show request/attempt/wait/effect/outcome/delivery with
bounded history and honest unknown/reconnect behavior. Local scripted speech uses
actual WebRTC audio from an explicitly selected bundled WAV through WebAudio,
without model/carrier credentials. The public RoomIO readiness barrier precedes
speech/controls; session_host=False removes alternate unbound SDK ingress.
Explicit End retires the room, and a fresh consumer resumes the same durable case.
Physical microphone quality and human hearing remain unqualified; selected
provider_real v2 inference has separate passing Phase H evidence. Read the
[conversation guide](../../docs/conversation-and-showcase.md) and
[Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
for local commands, tests and the current combined gate. The completed Phase H release separately qualifies artifacts, workloads and
selected provider inference; scripted media alone supplies no such claim.
