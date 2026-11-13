# Standalone repository and local transport foundation

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Create an independent ecosystem repository with a dedicated local-setup folder,
frozen toolchains, isolated Docker services and executable development checks.
Deliver an actual local API/LiveKit/agent/browser foundation for the three fixed
project charters. This is infrastructure progress under PLAN-09–PLAN-11, not
completion of a P1, P2 or P3 product acceptance case. All 54 product cases remain
planned; BASE-01 continues to establish the original M1 intake behavior.

## Interfaces and ownership

The control API owns local operator authentication, room-scoped five-minute
LiveKit tokens, named diagnostic dispatch and the existing M1 HTTP adapter. M1
SQLite remains authoritative for investigation intake. PostgreSQL is provisioned
with separate bootstrap/runtime credentials and a restricted runtime role, ready
for future schema decisions. No automatic migration or destructive conversion is
introduced.

The native Python Agents worker owns bounded transport diagnostics: text echo and
actual incoming audio-frame counts. It performs no STT/LLM/TTS inference. The
TypeScript console owns browser connection lifecycle and explicit microphone
permission. Credentials remain in browser memory and private ignored local files.

The local manager validates dotenv as data, exact image digests, ports, credential
permissions and checkout ownership before lifecycle mutation. Core services use
health checks, finite startup/shutdown budgets, dropped capabilities, nonroot
processes, bounded resources and logs. Stop preserves this project's named
volumes. Reset requires its own literal confirmation. Optional Jaeger verifies UI
readiness; trace export and retained production telemetry are future work.

See [local setup design](../../local-setup/Design.md),
[shared design](../../Design.md), [technology baseline](../technology-baseline.md)
and [build plan](../build-plan.md).

## Failure cases and validation

- Isolated tests reject invalid/duplicate config, environment substitution,
  unsafe credential permissions, malformed image digests, foreign-checkout
  containers and reset without its explicit confirmation.
- API tests verify authentication, bounded inputs, scoped grants, rate limits,
  replay/conflict, dependency failure and I/O cancellation capacity.
- SDK tests bound streams/tasks and assert diagnostic routing and audio cleanup.
  A fresh-interpreter serialization regression protects spawned worker startup.
- Console tests cover configuration/session validation, bounded UTF-8 streams and
  log capacity. TypeScript compilation and a production build exercise the native
  browser SDK dependency.
- Actual Compose smoke requires readiness, rejected invalid authentication,
  stable intake identity, conflict rejection, named agent join, correct text echo
  and synthetic audio reported by the agent for the published track. Timeouts,
  reader errors and failed cleanup cannot become successful smoke results.
- Stop/start must retain the same M1 identity under the smoke idempotency key.
  Never use reset to establish restart persistence.

Run from the repository root after the documented bootstrap:

```sh
make check
make format-check
pnpm check
pnpm test
pnpm build
.venv/bin/python -m harness run BASE-01
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh
python3.14 local-setup/stack.py doctor
python3.14 local-setup/stack.py start --observability
python3.14 local-setup/stack.py smoke
```

The deep gate must return incomplete/exit 2 while the 54 product cases are
unimplemented. Store disposable command output under ignored .local/validation;
never record generated bearer tokens or the complete environment.

## Results and handoff

Implemented the repository layout, service/app boundaries, per-area instructions,
local topology, lifecycle manager, immutable image selections, dependency locks,
root task commands and a CI workflow definition. Native SDK text and fixture
audio checks passed both inside Docker and from the host against the real local
LiveKit server/worker. The browser page loaded; authenticated browser microphone
and reconnect behavior remain unverified. PostgreSQL runtime role inspection
confirmed no superuser, database-creation or role-creation privileges. Optional
Jaeger returned HTTP 200; this is UI readiness evidence only.

Final-location frozen bootstrap and validation passed: 94 Python tests, 13
console tests, strict TypeScript, Ruff lint/format and mypy for eight service
source files. Documentation validation checked 44 documents with zero violations.
The acceptance catalog contains 55 scenarios: BASE-01 passed and the 54 product
scenarios reported not_implemented with the required incomplete/exit 2 result.

The repository was started from its final Downloads location. All five core
containers became healthy; optional Jaeger returned HTTP 200. Actual final-stack
container smoke passed authentication, M1 replay/conflict, named dispatch, text
echo and reception of at least ten synthetic audio frames. The same investigation
identity survived the preserve-state stop/start and relocation. Before ownership
labels were introduced, stopped synthetic fixture volumes were copied and
verified for content, permissions and ownership; no investigation state was reset.
Persistent-volume ownership and truncated-log redaction review findings were
resolved with positive and negative regression coverage.

Disposable evidence is under .local/validation: fast.txt, format.txt,
container-smoke.json, host-smoke.json, product-deep.json and restart-persistence.json.
Remote CI has not been executed. No cross-platform capacity, model quality,
workflow recovery or complete product-release claim follows from this foundation.
The work used AI assistance and independent implementation/documentation review.

Next implement PLAN-01–PLAN-03: versioned schema decisions, independent inquiry
execution and crash recovery while preserving existing M1 records and
investigation-only permission. Introduce real models, SMS adapters and specialist
services through their own scoped acceptance milestones.
