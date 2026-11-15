# Qualification gates and optional profiles

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Collect the opt-in qualification commands and optional runtime profiles that the root README only summarizes |
| Audience | Engineers who need to run a gate or start an optional profile |
| Scope | Shared lanes, P1 profiles and deep gates, opt-in P2/P3 gates and registered runners; excludes exact counts and evidence, which work items own |
| Owns | Index of opt-in qualification commands, optional runtime profiles and registered acceptance runners |
| Related | [Root README](../README.md) · [Local setup guide](../local-setup/README.md) · [Provider operations guide](provider-demo.md) · [Checkpoint history](checkpoint-history.md) · [Acceptance catalog](../harness/catalog.json) |

This guide collects the opt-in qualification commands and optional runtime
profiles that the [root README](../README.md) only summarizes. It is for engineers
who need to run a gate or start an optional profile.

- Every command runs from the repository root after frozen dependency setup
  (`make bootstrap` and `corepack pnpm install --frozen-lockfile`).
- Gates that need Docker LiveKit or PostgreSQL also need the documented local
  stack and restricted database roles from the
  [local setup guide](../local-setup/README.md).
- Work items own exact counts, failures and evidence. A passing selected gate never
  completes a whole charter row.
- Each Status cell names the work item that recorded the gate's selected result.
  Rerun a gate when its behavior or inputs change.

## Shared lanes

```sh
make check
make frontend-check
make postgres-check
make p2-postgres-check
```

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Fast lane | `make check` | Structural and documentation checks, all implemented offline Python suites, maintained lint and service/core type checks | Passed in [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |
| Frontend lane | `make frontend-check` | TypeScript, Vitest, formatting and production builds | Passed in [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |
| P1 real database | `make postgres-check` | The P1 real-database gate | Passed in [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |
| P2 real database | `make p2-postgres-check` | The separate P2 real-database lane | Passed in [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |

Missing setup, skipped or timed-out assertions cannot pass.

## P1 profiles and deep gates

| Profile | Enabled by | Start only after |
| --- | --- | --- |
| p1-workers | `start-workers`, which the setup guide owns | Preparing a deliberately selected ACTIVE v4 or v5 schema and its independent supplier/receiver fixtures |
| p1-business | The separate `start-business` command | Explicit ACTIVE v4 or v5 preparation (`prepare-business` takes the additive v5 step) and fixture initialization |

### Worker profile

The optional p1-workers profile is separate from normal foundation startup.

- The setup guide owns `start-workers`, `stop-workers` and preserved-volume
  restart.
- Workers receive only restricted runtime credentials.
- Startup never initializes or upgrades a supplier or database.

### Business workspace

- The workspace always authenticates current-case reads.
- Exact opaque quote approval stays in an explicit UI command.
- Model statements, playback and session End grant no mutation or cancellation
  authority.
- A later Join uses a fresh room, participant and invocation for the same durable
  task.

### Provider-real profile and deep gates

The explicit provider_real profile uses Deepgram nova-3, OpenAI gpt-5.4-mini and
ElevenLabs eleven_v4_turbo with three private keys. Follow the
[provider operations guide](provider-demo.md) for setup, check, start, stop and the
fresh P1-20 gate. Unprefixed deep commands keep P1-20's default local_real profile,
which remains unqualified:

```sh
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
P1_ACCEPTANCE_REAL_PROFILE=provider_real HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
```

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| P1 deep gate, default profile | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1` | Real PostgreSQL and browser/inference lanes, with P1-20 on local_real | Not qualified: local_real remains unqualified |
| P1 deep gate, provider_real | `P1_ACCEPTANCE_REAL_PROFILE=provider_real HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1` | The same lanes, with P1-20 on provider_real | P1 V1 qualified in [0019](work-items/0019-p1-phase-h-release-qualification.md); P1-20 open after the v5 rerun in [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |

If an approved public certificate authority (CA) bundle is needed, set
`P1_PROVIDER_CA_BUNDLE` as described in the
[provider guide](provider-demo.md#explicit-local-certificate-trust).

### Phase demonstrations and benchmarks

Phase demonstrations run isolated state.

| Task | Command | Notes |
| --- | --- | --- |
| Phase D, E and F demonstrations | `make phase-d-demo`, `make phase-e-demo`, `make phase-f-demo` | Each runs isolated state |
| Phase G demonstration | `make phase-g-demo` | Run after its documented image and host-asset rebuilds |
| Validate the frozen H1 workload | `make p1-benchmark-plan` | The H1 workload is the Phase H1 inquiry baseline; the plan validates it without running it |
| Measure the installed service | `make p1-benchmark` | Opt-in installed-service measurement |

## P2 and P3 backend gates

These gates use synthetic case/policy adapters, restricted-role local PostgreSQL
and the pinned Node toolchain. They grant no delivery or booking action unless
stated.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| P2 standalone examples | `make p2-demo` | Standalone public examples | Passed in [0027](work-items/0027-p2-standalone-and-p3-http.md) |
| P3 scripted request | `make p3-demo` | One scripted local HTTP request | Passed in [0027](work-items/0027-p2-standalone-and-p3-http.md) |
| P2 dispatch | `make p2-dispatch-check` | Bounded v2 claim/recovery | Passed in [0028](work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P3 coordinator | `make p3-coordinator-check` | Actual P1-backed submission and cross-language transport | Passed in [0028](work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P2 gateway | `make p2-gateway-check` | Gateway acknowledgement, forced exit and restart | Passed in [0029](work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| P3 execution | `make p3-execution-check` | v1-to-v2 upgrade and P1-issued invocation | Passed in [0029](work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| P2 agent | `make p2-agent-check` | Scripted-agent termination and replay | Passed in [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P3 completion | `make p3-completion-check` | Receiver acceptance and separately confirmed guarded action | Passed in [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P2 routing | `make p2-routing-check` | Standalone and P1 revision routing by case compare-and-set (CAS) | Passed in [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P3 contract | `make p3-contract-check` | P3-03 and P3-11 direct components | Passed in [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P2 communication | `make p2-communication-check` | Playback evidence: inbox v7 communication storage, migration and recovery | Passed in [0037](work-items/0037-playback-evidence-and-process-recovery.md) |
| P2 playback | `make p2-playback-check` | Playback evidence: actual local scripted playback with source-separated observations | Passed in [0037](work-items/0037-playback-evidence-and-process-recovery.md) |
| P3 recovery | `make p3-recovery-check` | Process recovery | Passed in [0037](work-items/0037-playback-evidence-and-process-recovery.md) |
| P3 deadlines | `make p3-deadlines-check` | Deadline and cancellation schedules | Passed in [0036](work-items/0036-native-input-and-deadline-cancellation.md) |
| P2 workload plan | `make p2-workload-plan` | Frozen workload inventory ([0039](work-items/0039-bounded-channel-workloads-and-image-evidence.md)), validated without running the workload | Plan only |
| P3 document plan | `make p3-document-plan` | Frozen document inventory ([0039](work-items/0039-bounded-channel-workloads-and-image-evidence.md)), printed without running the cases | Plan only |

## Native media and package gates

```sh
make p2-native-build
make p2-native-check
make p2-rehydration-check
make p2-rehydration-media-check
make p3-package-check
make p3-package-lab-check
```

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| P2 native build | `make p2-native-build` | Creates the isolated `p2-native.html` entry; starts no service | Passed in [0036](work-items/0036-native-input-and-deadline-cancellation.md) |
| P2 native media | `make p2-native-check` | The host software development kit (SDK), browser and gateway against local Docker LiveKit/PostgreSQL | Passed in [0036](work-items/0036-native-input-and-deadline-cancellation.md) |
| P2 rehydration storage | `make p2-rehydration-check` | Isolated PostgreSQL current-case rehydration | Passed in [0038](work-items/0038-case-rehydration-and-standalone-release.md) |
| P2 rehydration media | `make p2-rehydration-media-check` | Scripted speech-to-text, large language model and text-to-speech (STT/LLM/TTS) fixtures and local fake SMS | Passed in [0038](work-items/0038-case-rehydration-and-standalone-release.md) |
| P3 package | `make p3-package-check` | Builds and installs the P3 package offline | Passed in [0038](work-items/0038-case-rehydration-and-standalone-release.md) |
| P3 package lab | `make p3-package-lab-check` | Adds eight actual local completion/replay assertions to the offline check | Passed in [0038](work-items/0038-case-rehydration-and-standalone-release.md) |

- In the rehydration media check, the restored case, history and communication
  are separately timed observations.
- Scripts never read provider credentials.

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

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Receiver plan | `make p2-result-receiver-plan` | The receiver gate plan; starts no resources | Plan only |
| Receiver gate | `make p2-result-receiver-check` | Sixteen storage and four return assertions, with original-receipt reconciliation and populated backup/restore | Passed in [0043](work-items/0043-stable-result-delivery-and-return-context.md) |
| Receiver package | `make p2-result-receiver-package-check` | Isolated offline package consumers; no actual PostgreSQL or media assertions | Passed in [0043](work-items/0043-stable-result-delivery-and-return-context.md) |
| Origin plan | `make channel-origin-plan` | The origin gate plan; inert | Plan only |
| Origin unit suites | `make channel-origin-unit` | The root and P3 origin unit tests | Passed in [0044](work-items/0044-origin-bound-channel-policy.md) |
| Origin gate | `make channel-origin-check` | Native and signed simulated-SMS input joined to original P1 work, issued policy results and the current P2 receipt/read | Passed in [0044](work-items/0044-origin-bound-channel-policy.md) |
| Origin package | `make channel-origin-package-check` | Built and installed public artifacts with explicit fake ports | Passed in [0044](work-items/0044-origin-bound-channel-policy.md) |

- The origin gate uses three disposable schemas and one owned kill of the
  acknowledgement (ACK) host after commit.
- Reports use fresh timestamped paths under `.local/validation`. Failed runs are
  kept.

## Joined showcase

The joined application composes those seams
([0045](work-items/0045-joined-native-channel-policy.md),
[0046](work-items/0046-joined-showcase-providers-and-demo.md)). Its commands are in
the root README [quickstart](../README.md#quickstart) and
[commands](../README.md#commands) sections. The work items record its source,
installed and media gates. Recording the demo video is not a qualification gate.

## Registered acceptance runners

```sh
.venv/bin/python -m harness validate
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Catalog metadata | `.venv/bin/python -m harness validate` | Validates catalog metadata and prints the case and registration counts | Valid in [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |
| BASE-01 | `.venv/bin/python -m harness run BASE-01` | Existing M1 confirmed investigation intake tests | Passed in [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| P3-01 | `.venv/bin/python -m harness run P3-01` | Current issued useful result, durable receiver and exactly confirmed fake action | Passed in [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P3-03 | `.venv/bin/python -m harness run P3-03` | Concurrent scoped delegation replay and changed-payload conflict | Passed in [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P3-11 | `.venv/bin/python -m harness run P3-11` | Complete bounded schema, scope, context, image and result rejection inventory | Passed in [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) |
| Fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | The selected structural groups and all implemented Python suites | Passed in [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) within `make check` |

The [catalog](../harness/catalog.json) owns executable registrations. All twenty
P1 rows have registered runners. Seventeen P2 and fourteen P3 rows remain planned,
so the project and ecosystem aggregates stay incomplete by design.
