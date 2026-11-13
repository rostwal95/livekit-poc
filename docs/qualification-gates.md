# Qualification gates and optional profiles

Status: Active
Last reviewed: 13 November 2026

This guide collects the opt-in qualification commands and optional runtime
profiles that the [root README](../README.md) only summarizes. Every command runs
from the repository root after frozen dependency setup (`make bootstrap` and
`corepack pnpm install --frozen-lockfile`). Gates that need Docker LiveKit or
PostgreSQL also need the documented local stack and restricted database roles from
the [local setup guide](../local-setup/README.md). Work items own exact counts,
failures and evidence; a passing selected gate never completes a whole charter row.

## Shared lanes

The fast lane runs structural/documentation checks and all implemented offline
Python suites, plus maintained lint and service/core type checks. Frontend checks
run TypeScript, Vitest and production builds.

```sh
make check
make frontend-check
make postgres-check
make p2-postgres-check
```

`make postgres-check` runs the P1 real-database gate and `make p2-postgres-check`
the separate P2 lane. Missing setup, skipped or timed-out assertions cannot pass.

## P1 profiles and deep gates

The optional p1-workers profile is separate from normal foundation startup. Start
it only after preparing a deliberately selected ACTIVE v4 schema and its
independent supplier/receiver fixtures; the setup guide owns start-workers,
stop-workers and preserved-volume restart. Workers receive only restricted runtime
credentials, and startup never initializes or upgrades a supplier or database.

The separate start-business command enables the p1-business profile only after
explicit ACTIVE v4 preparation and fixture initialization. The workspace always
authenticates current-case reads and keeps exact opaque quote approval in an
explicit UI command. Model statements, playback and session End grant no
mutation or cancellation authority. A later Join uses a fresh room, participant and
invocation for the same durable task.

The explicit provider_real profile uses Deepgram nova-3, OpenAI gpt-5.4-mini and
ElevenLabs eleven_v4_turbo with three private keys. Follow the
[provider operations guide](provider-demo.md) for setup, check, start, stop and the
fresh P1-20 gate. Unprefixed deep commands keep P1-20's default local_real profile,
which remains unqualified:

```sh
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
P1_ACCEPTANCE_REAL_PROFILE=provider_real HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
```

If an approved public CA bundle is needed, set P1_PROVIDER_CA_BUNDLE as described
in the [provider guide](provider-demo.md#explicit-local-certificate-trust).

Phase demonstrations run isolated state: `make phase-d-demo`, `make phase-e-demo`,
`make phase-f-demo` and `make phase-g-demo` (the last after its documented image
and host-asset rebuilds). `make p1-benchmark-plan` validates the frozen H1 workload
without running it; `make p1-benchmark` is the opt-in installed-service measurement.

## P2 and P3 backend gates

These use synthetic case/policy adapters, restricted-role local PostgreSQL and the
pinned Node toolchain. They grant no delivery or booking action unless stated.

| Command | Scope |
| --- | --- |
| `make p2-demo` / `make p3-demo` | Standalone public examples and one scripted local HTTP request |
| `make p2-dispatch-check` / `make p3-coordinator-check` | Bounded v2 claim/recovery; actual P1-backed submission and cross-language transport |
| `make p2-gateway-check` / `make p3-execution-check` | Gateway acknowledgement/forced exit/restart; v1-to-v2 upgrade and P1-issued invocation |
| `make p2-agent-check` / `make p3-completion-check` | Scripted-agent termination/replay; receiver acceptance and separately confirmed guarded action |
| `make p2-routing-check` / `make p3-contract-check` | Standalone/P1 case-CAS revision routing; P3-03/P3-11 direct components |
| `make p2-communication-check`, `make p2-playback-check`, `make p3-recovery-check` | Playback evidence and process recovery (0037) |
| `make p3-deadlines-check` | Deadline and cancellation schedules (0036) |
| `make p2-workload-plan`, `make p3-document-plan` | Frozen workload and document inventories (0039) |

## Native media and package gates

```sh
make p2-native-build
make p2-native-check
make p2-rehydration-check
make p2-rehydration-media-check
make p3-package-check
make p3-package-lab-check
```

The build creates the isolated p2-native.html entry; it starts no service. The
native check exercises the host SDK, browser and gateway against local Docker
LiveKit/PostgreSQL. Rehydration media uses scripted STT/LLM/TTS and local fake SMS;
restored case, history and communication are separately timed observations. The
P3 package command builds and installs offline; its lab variant adds eight actual
local completion/replay assertions. Scripts never read provider credentials.

## Result delivery and original-input binding

```sh
make p2-result-receiver-plan
make p2-result-receiver-check
make p2-result-receiver-package-check
make channel-origin-plan
make channel-origin-unit
make channel-origin-check
make channel-origin-package-check
```

The receiver gate owns sixteen storage and four return assertions with original-
receipt reconciliation and populated backup/restore ([0043](work-items/0043-stable-result-delivery-and-return-context.md)).
The origin gate joins native and signed simulated-SMS input to original P1 work,
issued policy results and the current P2 receipt/read, with three disposable
schemas and one owned post-commit ACK-host kill ([0044](work-items/0044-origin-bound-channel-policy.md)).
Reports use fresh timestamped paths under .local/validation; failed runs are kept.

## Joined showcase

The joined application composes those seams ([0045](work-items/0045-joined-native-channel-policy.md),
[0046](work-items/0046-joined-showcase-providers-and-demo.md)). Its commands are in
the README quick start. Its source, installed and media gates are recorded in the
work items; recording the demo video is not a qualification gate.

## Registered acceptance runners

```sh
.venv/bin/python -m harness validate
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

The [catalog](../harness/catalog.json) owns executable registrations. All twenty
P1 rows have registered runners; seventeen P2 and fourteen P3 rows remain planned,
so the project and ecosystem aggregates stay incomplete by design.
