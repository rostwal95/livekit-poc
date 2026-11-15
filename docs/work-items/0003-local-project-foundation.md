# Standalone repository and local transport foundation

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the standalone repository and local transport foundation |
| Audience | Engineers changing local setup, the control API, the diagnostic worker or the console; coding agents |
| Scope | Repository layout, local topology, control API, diagnostic worker and console under PLAN-09–PLAN-11; excludes any P1, P2 or P3 product acceptance case |
| Owns | Change plan, observed verification and handoff for the local project foundation |
| Related | [Work item 0002](0002-documentation-audit.md) · [Work item 0004](0004-plan-and-showcase-audit.md) · [Local setup design](../../local-setup/Design.md) · [Build plan](../build-plan.md) |

## Behavior and scope

Create an independent ecosystem repository with a dedicated local-setup folder,
frozen toolchains, isolated Docker services and executable development checks.
Deliver an actual local API, LiveKit, agent and browser foundation for the three
fixed project charters. This is infrastructure progress under build-plan work
packages PLAN-09–PLAN-11, not completion of a P1, P2 or P3 product acceptance
case. All 54 product cases remain planned. The BASE-01 baseline case continues to
establish the original M1 intake behavior (the SQLite confirmed-investigation
intake).

## Interfaces and ownership

| Component | Responsibility |
| --- | --- |
| Control API | Local operator authentication, room-scoped five-minute LiveKit tokens, named diagnostic dispatch and the existing M1 HTTP adapter |
| M1 SQLite | Remains authoritative for investigation intake |
| PostgreSQL | Provisioned with separate bootstrap and runtime credentials and a restricted runtime role, ready for future schema decisions |
| Native Python Agents worker | Bounded transport diagnostics: text echo and actual incoming audio-frame counts |
| TypeScript console | Browser connection lifecycle and explicit microphone permission |
| Local manager | Validates dotenv content as data, exact image digests, ports, credential permissions and checkout ownership before lifecycle mutation |

No automatic migration or destructive conversion is introduced. The native worker
performs no speech-to-text (STT), large language model (LLM) or text-to-speech
(TTS) inference. Credentials remain in browser memory and private ignored local
files.

Core services use health checks, finite startup and shutdown budgets, dropped
capabilities, nonroot processes, bounded resources and logs. Stop preserves this
project's named volumes. Reset requires its own literal confirmation. Optional
Jaeger verifies UI readiness. Trace export and retained production telemetry are
future work.

See [local setup design](../../local-setup/Design.md),
[shared design](../../Design.md), [technology baseline](../technology-baseline.md)
and [build plan](../build-plan.md).

## Failure cases and validation

- Isolated tests reject invalid or duplicate config, environment substitution,
  unsafe credential permissions, malformed image digests, foreign-checkout
  containers and reset without its explicit confirmation.
- API tests verify authentication, bounded inputs, scoped grants, rate limits,
  replay and conflict, dependency failure and I/O cancellation capacity.
- SDK tests bound streams and tasks and assert diagnostic routing and audio
  cleanup. A fresh-interpreter serialization regression protects spawned worker
  startup.
- Console tests cover configuration and session validation, bounded UTF-8 streams
  and log capacity. TypeScript compilation and a production build exercise the
  native browser SDK dependency.
- Actual Compose smoke requires readiness, rejected invalid authentication, stable
  intake identity, conflict rejection, named agent join, correct text echo and
  synthetic audio reported by the agent for the published track. Timeouts, reader
  errors and failed cleanup cannot become successful smoke results.
- Stop and start must retain the same M1 identity under the smoke idempotency key.
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

The deep gate must return incomplete (exit 2) while the 54 product cases are
unimplemented. Store disposable command output under the ignored
`.local/validation` directory. Never record generated bearer tokens or the
complete environment.

## Results and handoff

Implemented the repository layout, service and app boundaries, per-area
instructions, local topology, lifecycle manager, immutable image selections,
dependency locks, root task commands and a continuous integration (CI) workflow
definition.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Fast validation | Frozen bootstrap and validation at the final location | Passed: 94 Python tests, 13 console tests, strict TypeScript, Ruff lint and format checks, and mypy for eight service source files |
| Documentation | Documentation validation | 44 documents checked with zero violations |
| Acceptance catalog | Catalog and deep gate | 55 scenarios; BASE-01 passed; the 54 product scenarios reported not_implemented with the required incomplete result (exit 2) |
| Native transport | Native SDK text and fixture audio checks | Passed both inside Docker and from the host against the real local LiveKit server and worker |
| Stack health | Start from the final Downloads location | All five core containers became healthy; optional Jaeger returned HTTP 200 |
| Container smoke | Actual final-stack container smoke | Passed authentication, M1 replay and conflict, named dispatch, text echo and reception of at least ten synthetic audio frames |
| Restart persistence | Preserve-state stop and start, and the relocation | The same investigation identity survived |
| PostgreSQL role | Runtime role inspection | No superuser, database-creation or role-creation privileges |

The browser page loaded. Authenticated browser microphone and reconnect behavior
remain unverified. The optional Jaeger HTTP 200 is UI readiness evidence only.

Before ownership labels were introduced, stopped synthetic fixture volumes were
copied and verified for content, permissions and ownership. No investigation
state was reset. Persistent-volume ownership and truncated-log redaction review
findings were resolved with positive and negative regression coverage.

### Evidence and next step

Disposable evidence is under `.local/validation`:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast validation output |
| `format.txt` | Format check output |
| `container-smoke.json` | Container smoke result |
| `host-smoke.json` | Host smoke result |
| `product-deep.json` | Deep product gate result |
| `restart-persistence.json` | Preserve-state restart result |

Remote CI has not been executed. No cross-platform capacity, model quality,
workflow recovery or complete product-release claim follows from this foundation.
The work used AI assistance and independent implementation and documentation
review.

Next, implement PLAN-01–PLAN-03: versioned schema decisions, independent inquiry
execution and crash recovery. Preserve existing M1 records and investigation-only
permission. Introduce real models, SMS adapters and specialist services through
their own scoped acceptance milestones.
