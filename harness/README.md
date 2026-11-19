# Ecosystem development harness

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to run the harness, read its outcomes and see which acceptance cases have registered runners |
| Audience | Contributors and coding agents who run the harness, read its reports or add a runner |
| Scope | Harness commands, outcome rules, runner registrations and selected local gates; excludes harness architecture and product requirements |
| Owns | Implemented harness CLI, exact harness commands, exit codes and outcome semantics |
| Related | [Harness design](Design.md) · [Harness agent rules](AGENTS.md) · [Harness architecture](../docs/harness-architecture.md) · [Validation plan](../docs/validation-plan.md) · [Documentation standards](../docs/documentation-standards.md) |

## Overview

The harness is the repository's structural checker, scenario runner and evidence
recorder. It discovers product requirements, checks repository contracts and runs
implemented tests through a bounded local interface. Structural validation and
product acceptance have separate outcomes. A structural pass never certifies
product behavior.

This guide is for contributors and coding agents who run the harness, read its
reports or add a runner. It lists the working commands, explains what each outcome
means and records which acceptance cases have registered runners.
[Design.md](Design.md) explains the architecture behind these commands.

Contents:

- [Implementation status](#implementation-status): implemented checks, the
  acceptance catalog and completed selected phase gates.
- [Documentation](#documentation): related guides.
- [Requirements](#requirements): environment, interpreter and per-gate setup.
- [Commands](#commands): structural checks, acceptance runs and explicit local
  gates.
- [Validation](#validation): outcome rules, checks, runner kinds, reports and
  evidence boundaries.
- [Next milestone](#next-milestone): work that remains.

### Terms used in this guide

| Term | Meaning |
| --- | --- |
| Acceptance case | A required behavior with a stable ID. `BASE-01` is the baseline. IDs such as `P1-01` come from the P1, P2 and P3 project charters. |
| Charter row | The table row for one acceptance ID in a project charter under `docs/projects`. The harness parses these rows into its catalog. |
| Catalog | [catalog.json](catalog.json): the 55 case definitions and the runners registered for them. |
| Registered runner | A catalog entry that executes a case's actual assertions. |
| Selected phase gate | An explicit local check for one implementation slice. Complete charter registration still requires every normative row assertion. |
| Task ID | An implementation task such as `P2-I14`, `P1-I27` or `S-I06` from the [granular roadmap](../docs/implementation-plan.md). |
| Execution mode | offline, lab or live, as defined in the [portfolio scope](../docs/portfolio-scope.md). |
| Inference profile | scripted (default), local_real or provider_real. |
| M1 | The existing confirmed-investigation intake. |
| V1 and POC | V1 is the fixed project scope. POC is this local proof of concept. |
| Phases E to H | P1 build phases, each with work items under [docs/work-items](../docs/work-items). |
| Phase E | Supplier effects. |
| Phase F | Leases and workers. |
| Phase G | Conversation and traces. |
| Phase H | H1 (inquiry workload baseline), H2 (restart and slow-supplier workloads), H3 (standalone package) and release qualification. |

## Implementation status

### Implemented checks

| Capability | Status | Evidence |
| --- | --- | --- |
| Mandatory infrastructure ownership and entrypoint checks | Implemented | [Static checker fixtures](../tests/test_harness_static.py) |
| Product module contracts | Implemented | [Static checker fixtures](../tests/test_harness_static.py) |
| Documentation checks (document card, role sections and tables, links) | Implemented | [Documentation checker fixtures](../tests/test_documentation.py) |
| Known import boundaries | Implemented | [Static checker fixtures](../tests/test_harness_static.py) |
| Negative fixtures | Implemented | Fixture suites under [tests](../tests) |
| Acceptance discovery and unittest execution | Implemented | [Engine fixtures](../tests/test_harness.py) |
| Root frontend commands and local setup smoke | Implemented | [Frontend, smoke and quality lanes](#frontend-smoke-and-quality-lanes) |
| H1 workload model | Implemented | [Workload model fixtures](../tests/test_workload_models.py) |
| H1 inquiry measurement | Qualified | Local inquiry baseline in the [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) |

Separate root frontend commands and the local setup smoke verify the implemented
console and transport foundation. These checks are not registered as completion of
the planned product scenarios.

The dependency-free H1 workload model validates frozen seeded declarations. Its
explicit local-setup consumer measures installed inquiry services in a separate
lane. No benchmark runner is registered as a complete charter row.

### Catalog and registered runners

The catalog has 24 registrations of 55 cases: BASE-01, 20 P1 and 3 P3. The catalog
owns current complete runner registrations. Full product coverage remains pending.

| Project | Cases | Registered runners | Status | Evidence |
| --- | --- | --- | --- | --- |
| Baseline | 1 (`BASE-01`) | 1 | Implemented | Runs the [M1 intake tests](../tests/test_intake.py) |
| P1 agent continuity | 20 (`P1-01` to `P1-20`) | 20 | Qualified | Retained P1-01 through P1-20 reports passed |
| P2 channel continuity | 17 | 0 | Planned | No registered runner |
| P3 delegation reliability | 17 | 3 (`P3-01`, `P3-03`, `P3-11`) | Partial: 14 rows planned | Complete lab runners with retained passing reports |

All 17 P2 rows and the remaining 14 P3 rows stay planned, so full aggregates remain
incomplete.

All twenty P1 charter rows have registered runners. They combine SQLite process
suites, exact PostgreSQL assertion mappings and fresh infrastructure reports:

| Cases | Runner kind and mode | What runs |
| --- | --- | --- |
| `BASE-01` | `unittest_discovery` | M1 intake tests |
| `P1-01`, `P1-02`, `P1-03` | `unittest_discovery` | The shared five-test accepting-process suite |
| `P1-04`, `P1-05` | `unittest_discovery` | The shared four-test independent supplier/worker suite |
| `P1-06` to `P1-13`, `P1-15` to `P1-17`, `P1-19` | `python_json_report`, lab | Exact PostgreSQL assertion mappings |
| `P1-14`, `P1-18` | `python_infrastructure_report`, lab | Fresh infrastructure reports |
| `P1-20` | `python_infrastructure_report`, live | Fresh real-inference report for the selected profile |
| `P3-01`, `P3-03`, `P3-11` | `python_json_report`, lab | Fresh 13-, 8- and 12-assertion components |

P1 V1 is qualified for the local POC using provider_real v2. local_real remains
unqualified.

The [current P1 qualification summary](../docs/build-plan.md#p1-qualification)
distinguishes that retained release from the later booking-v5 rerun, whose fresh
P1-20 provider result remains open.

### Completed selected phase gates

The phases below completed their selected local gates. A selected gate adds
evidence for one implementation slice. No test count, structural result or
selected phase gate registers a full product row, and catalog registrations remain
24 of 55.

| Gate | Assertion or lane | Evidence | Status |
| --- | --- | --- | --- |
| Linked confirmation and result projections | P2/P3 gates and work-profile v4 tests | [Work item 0032](../docs/work-items/0032-linked-confirmation-and-result-projections.md) | Qualified (selected local) |
| Outbound replies and completion processing | 24 P2 and 16 P3 named assertions and isolated installed consumers | [Work item 0033](../docs/work-items/0033-outbound-replies-and-completion-processing.md) | Qualified (selected local) |
| Send policy and action races | P2-I14 and P3-I12 gates | [Work item 0035](../docs/work-items/0035-send-policy-and-action-races.md) | Qualified (selected local) |
| Native input and deadline cancellation | P2 six-group native gate and P3 temporal assertions | [Work item 0036](../docs/work-items/0036-native-input-and-deadline-cancellation.md) | Qualified (selected) |

Later selected gates (playback and process recovery, result receivers, original
channel input, workloads and documents, operations and fixed policy) are described
with their commands under [Commands](#commands).

#### Linked confirmation and result projections

The [completed linked-confirmation/projection phase](../docs/work-items/0032-linked-confirmation-and-result-projections.md)
adds selected P2/P3 gates and work-profile v4 tests. Its selected local phase
qualification passed.

- Full Python validation includes the new public feed and bridge boundaries.
- The explicit PostgreSQL lane includes feed migration, crash and cursor tests and
  the existing regressions.

#### Outbound replies and completion processing

The [completed outbound-reply/processing phase](../docs/work-items/0033-outbound-replies-and-completion-processing.md)
completed its selected local P2/P3 gates. These include 24 P2 and 16 P3 named
assertions and isolated installed consumers.

- P2 owns communication attempts. P3 owns only processing metadata over existing
  public P1 identities.
- Exact role-separated child protocols, real process barriers, finite captures and
  owned cleanup passed.
- The catalog remains at 24 registrations of 55. No complete new row is implied.

The phase recorded these counts:

| Check | Recorded count |
| --- | --- |
| Python tests | 1,501 |
| TypeScript tests | 723 |
| Typing sources | 133 broad and 95 strict |
| Formatted Python files | 321 |

#### Send policy and action races

The [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Preserve the completed
[callback/applicability checkpoint](../docs/work-items/0034-callback-evidence-and-applicability-refresh.md).

The P2 gate requires 30 named actual assertions. They include populated inbox
v4-to-v5 migration and restore, ordinary unknown holds, cooperating same-key
retries, callback ordering and independent provider ledgers.

The P3 gate freezes 16 cases and 31 one-time modes, three owned process ID (PID)
kills and two actual two-waiter SQL order graphs. Its bounds are:

| Limit | Value |
| --- | --- |
| Total deadline | 180 seconds, including 15 seconds for cleanup |
| Children | At most 32 |
| Aggregate capture | 128 KiB |
| Capture per stream | 2 KiB |
| Final report | 32 KiB |

Rules for these gates:

- Prewarm both writers and the same owner locker/observer before lock contention.
  Never change P1's lock timeout.
- Validate exact keys and JSON primitive types, first-failure precedence,
  role-separated environments and complete cleanup.
- Optional diagnostic runs retain only bounded redacted failure streams. They
  always remain non-qualifying.
- Actual, isolated installed and prior regression gates passed for this slice.
  Require them again after affected changes.

The phase checkpoint passed these checks:

| Check | Result |
| --- | --- |
| Python tests | 1,660 passed: 49 P1, 14 P2, 238 P3 and 1,359 root |
| TypeScript tests | 861 passed: 326 console, 457 P2 and 78 specialists |
| Type sources | 138 broad and 108 strict passed |
| Ruff formatting | 340 files passed |
| Source gates | 30-case P2 and 16-case P3 passed |
| Isolated installed consumers | Passed |
| Prior regression assertions | 111 P2 and 101 P3 passed |

These are correctness checks, not production capacity or real-media measurements.

The phase introduces no complete charter registration and no P1/P3 runtime change.
Physical delivery and human acknowledgement (ACK) remain distinct from provider
evidence.

#### Native input and deadline cancellation

The [completed native/deadline handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
adds explicit optional gates. Their commands are under
[Native input and deadline gates](#native-input-and-deadline-gates).

- P2 passed the selected actual six-group native gate and the isolated Python/npm
  package gates.
- Focused checks passed 55 Python, 530 P2 TypeScript, 65 browser-policy and 45
  wrapper tests, plus one local HTTP proxy regression.
- Final selected phase regression and shared checks passed, as did the affected
  media rerun.
- P3's selected 18 source and 18 installed temporal assertions and 46
  compatibility assertions passed through unchanged P1/P3 production authority.
- Full product rows and registrations remain unchanged. The shared
  [validation plan](../docs/validation-plan.md) records the exact evidence.

## Documentation

Read these before changing the harness:

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Rules for coding agents working on the harness |
| [Design.md](Design.md) | Harness architecture, bounds and failure handling |
| [Harness architecture](../docs/harness-architecture.md) | Components, outcome semantics and scope selection |
| [Validation plan](../docs/validation-plan.md) | Test lanes, evidence and release requirements |
| [Documentation standards](../docs/documentation-standards.md) | Corpus, document card, required sections and tables by role, and link rules that the documentation checker enforces |

Guides for specific gates:

| Document | Purpose |
| --- | --- |
| [Local setup guide](../local-setup/README.md) | Local stack prerequisites |
| [Local-real operations guide](../docs/local-real-inference.md) | Real-inference preparation for P1-20 with local_real |
| [Provider operations guide](../docs/provider-demo.md) | Real-inference preparation for P1-20 with provider_real |
| [Observability guide](../docs/observability.md) | Interpretation of H1 workload measurements |
| Work items under [docs/work-items](../docs/work-items) | Exact evidence for each phase gate |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Working directory | Repository root | Run every command from the checkout root |
| Python environment | Python 3.14 in the frozen environment installed by `make bootstrap` | The harness engine uses only the Python standard library |
| Declared extras | All extras, as installed by `make bootstrap` | The full fast lane also discovers service tests, which require them |
| Interpreter selector | `HARNESS_PYTHON=.venv/bin/python` | Selects the same interpreter as the project environment |
| Credentials and remote services | None for offline checks | Offline checks require no credentials or remote services |
| Explicit local gates | Per gate | Restricted-role local PostgreSQL, the local stack, a pinned Node toolchain or provider keys |

Each subsection under [Commands](#commands) states the prerequisites of its own
explicit local gate.

## Commands

All commands run from the repository root.

### Structural checks and the fast lane

```sh
.venv/bin/python -m harness validate
.venv/bin/python -m harness list
.venv/bin/python -m harness list --project p1
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1 --groups boundary,contract
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --changed --base HEAD
```

| Task | Command | Notes |
| --- | --- | --- |
| Validate catalog metadata | `.venv/bin/python -m harness validate` | Prints the case and registration counts |
| List acceptance cases | `.venv/bin/python -m harness list` | `--project p1` limits the list to one project |
| Check documentation | `.venv/bin/python -m harness.documentation_check` | Runs the [documentation checker](#documentation-checker) |
| Run the fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Selected structural groups and all implemented Python suites |
| Focus structural inspection | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1 --groups boundary,contract` | One product and the named groups |
| Check the changed scope | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --changed --base HEAD` | Selects the affected scope from changes against a comparison baseline |

The fast lane checks the selected structural groups and all implemented Python
suites. The groups are docs, boundary and contract. Every selection still enforces
the mandatory foundation policy, as described in
[Foundation policy and scope selection](#foundation-policy-and-scope-selection).

### Acceptance runs and the deep lane

```sh
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P1-05
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh
```

| Task | Command | Notes |
| --- | --- | --- |
| Run the baseline case | `.venv/bin/python -m harness run BASE-01` | M1 intake tests |
| Run one registered case | `.venv/bin/python -m harness run P1-05` | Retains its independent supplier/worker assertions |
| Run the P1 deep lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1` | Requires actual PostgreSQL, browser/media and the selected real-inference setup |
| Run the full deep lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh` | Planned P2/P3 rows leave the aggregate incomplete |

- BASE-01, all of P1-01 through P1-20 and P3-01/P3-03/P3-11 have executable
  registered runners.
- Later PostgreSQL and infrastructure runners execute their exact mapped
  requirements.
- Catalog metadata is not a fresh result.
- P1-20 defaults to local_real. Use the documented trusted provider selector
  explicitly for provider_real, as shown in
  [Registered runtime acceptance](#registered-runtime-acceptance).
- P2/P3 planned rows still produce incomplete project and ecosystem aggregates
  with exit code 2.
- Keep missing or failed evidence non-passing. Remote continuous integration (CI)
  is outside the POC scope.

### Selected P3 lab cases

With the documented restricted-role local PostgreSQL and pinned Node setup:

```sh
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

| Task | Command | Notes |
| --- | --- | --- |
| Run P3-01 | `.venv/bin/python -m harness run P3-01` | Fresh 13-assertion component |
| Run P3-03 | `.venv/bin/python -m harness run P3-03` | Fresh 8-assertion component |
| Run P3-11 | `.venv/bin/python -m harness run P3-11` | Fresh 12-assertion component |

These commands execute fresh 13-, 8- and 12-assertion components through
[p3_acceptance.py](../local-setup/scripts/p3_acceptance.py). They do not reuse a
previous passed report. Each run validates:

- the exact named inventory and fixed lab mode
- zero required skips, errors and failures
- equality between standard output and the report file
- owned cleanup

The child environment excludes ambient provider, PostgreSQL, proxy and interpreter
selectors. Only explicit component orchestration receives local runtime and owner
setup. Raw child capture is bounded, private and ephemeral. Retain the component
path and hash and the fresh outer report.

These runs establish no image decoding, native media, new model qualification or
full P3 release. See the
[revision-routing and delegation-acceptance work item](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md).

### Registered runtime acceptance

P1-14, P1-18 and P1-20 use the `python_infrastructure_report` runner kind. Every
invocation creates new owned evidence.

| Case | Mode | What a run executes |
| --- | --- | --- |
| P1-14 | lab | The six-case scripted browser lane plus three post-commit database assertions |
| P1-18 | lab | The selected saturation/shutdown workload |
| P1-20 | live, for actual inference | The two-case browser/model lane for its trusted selected real profile |

P1-20 has two real profiles. Neither requires hosted LiveKit or a carrier.

| Profile | Inference | Provider keys | Status |
| --- | --- | --- | --- |
| local_real (default) | Prepared Whisper/Qwen/Piper | Not needed | Not qualified |
| provider_real (explicit) | Deepgram/OpenAI/ElevenLabs | Needed | Qualified: the selected v2 gate passed |

Every applicable actual assertion must pass independently of mode labels.

| Limit | Value |
| --- | --- |
| Infrastructure catalog ceiling | 900 seconds |
| Product wrapper | One original 840-second total deadline |
| Browser helper | 600 seconds of work and 180 seconds for cleanup |
| Ordinary runner ceiling | 300 seconds |

Neither an observation timeout nor a retry extends the original deadline.

The wrapper verifies current source/input provenance, actual raw browser runner
results, independent durable truth and cleanup. It cannot adopt a previous Phase G
or Phase H report. Missing setup, required skips, invalid modes, timeouts or
incomplete cleanup remain non-passing.

The fresh combined P1-14 pass is recorded in the
[Phase H release-qualification work item](../docs/work-items/0019-p1-phase-h-release-qualification.md).
Use the [local-real operations guide](../docs/local-real-inference.md) for explicit
preparation and the relevant work item for inspected actual results.

For external provider inference use the explicit trusted selector:

```sh
P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

The default remains local_real. Both profiles report live mode. Both retain the
same original work and cleanup deadlines, two actual browser cases and authority
assertions. The provider lane requires real software development kit (SDK) usage
and exact sanitized model/provider spans. It observes only native, API and worker
resources, so external provider CPU and memory are unknown. See the
[provider operations guide](../docs/provider-demo.md).

Neither mode has passing real-media qualification until its own fresh evidence
passes. The selected provider_real v2 gate has passed. local_real remains
unqualified.

### Phase H workload, reliability and package gates

#### Inquiry workload declaration (H1)

```sh
make p1-benchmark-plan
```

| Task | Command | Notes |
| --- | --- | --- |
| Validate the H1 declaration | `make p1-benchmark-plan` | Returns status `not_started` and starts no workload |
| Run the H1 inquiry workload | `make p1-benchmark` | Executes the installed HTTP/worker lane after the local prerequisites |

The plan target invokes `local-setup/scripts/p1_benchmark.py` without `--run`. It
validates the [versioned manifest](workloads/p1-inquiry-v1.json), prints its
canonical digest and six experiment names, and returns status `not_started`. It
starts no workload.

The standard-library [workload model](workload_models.py) rejects duplicate or
unknown fields, unsafe input, nonfinite or unbounded values and inconsistent
schedules or caps. Freeze the reviewed manifest and digest before measurement. Its
six modes declare 168 new offers, 120 admissions and 48 capacity rejections. These
are declared inputs, not actual outcomes.

`make p1-benchmark` explicitly executes the installed HTTP/worker lane after the
[local prerequisites](../local-setup/README.md). The runner belongs to local setup.
There is no new harness run ID or catalog registration for this partial workload.
A pass needs actual useful results, independent supplier reconciliation and owned
cleanup.

The [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) owns the
completed local inquiry measurement and inspected evidence. Full Phase H/P1 release
and broader workload qualification remain separate.
[Workload evidence boundaries](#workload-evidence-boundaries) explains how to read
the H1 artifacts.

#### Reliability and package gates (H2 and H3)

| Task | Command | Notes |
| --- | --- | --- |
| Validate the reliability declaration | `make p1-reliability-plan` | Validates the frozen reliability declaration without executing it |
| Run the reliability workloads | `make p1-reliability` | Runs its owned local fault workloads; the [reliability work item](../docs/work-items/0015-p1-reliability-workloads.md) owns actual results and limits |
| Check the standalone P1 package | `make p1-package-check` | Builds or rebuilds the standalone P1 artifacts and runs isolated installed consumers; the [package work item](../docs/work-items/0016-p1-standalone-package.md) owns its final local host/container qualification |

Neither a plan nor an artifact build alone completes a workload, media or release
assertion. Real models and media use their separate
[operations guide](../docs/local-real-inference.md).

### Phase G conversation and browser gate

| Task | Command | Notes |
| --- | --- | --- |
| Run the Phase G gate | `make phase-g-demo` | Installed native business profile through the real local browser and media, the current projection, exact UI approval and the inspected raw Jaeger v3 trace path |

The gate's
[work item](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) records
the inspected local combined gate.

What the gate does and does not establish:

- Explicit bundled-WAV WebAudio input and native scripted providers establish
  transport and lifecycle. They do not establish physical microphone or configured
  inference quality.
- The public RoomIO barrier and the native ready attribute gate the controls.
  Alternate SDK session hosting is disabled.
- Offline native/manual-audio and trace-wire tests remain separate from this lane.
- Hardware capture, automatic network-loss recovery and actual local-real
  engine/media evidence remain separate.
- Granular phase success alone does not pass a registered charter row or
  whole-project release.

Rules:

- The runner must fail missing browser, dependency or fault setup rather than skip
  it.
- Artifacts live under `.local/validation/p1-phase-g`. Keep credentials out of
  browser recordings and diagnostics.
- Remote CI and publication are outside the local POC scope.

### Native input and deadline gates

Run from the repository root after frozen dependency setup and the documented local
stack and restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Build the native page | `make p2-native-build` | Builds the P2 SDK, then the isolated `p2-native.html` entry to `dist-native`; starts no service and changes no default console entry |
| Run the native gate | `make p2-native-check` | Owns the selected qualified host SDK/browser/gateway exercise against local Docker LiveKit/PostgreSQL |
| Run the P3 deadline gate | `make p3-deadlines-check` | Runs the qualified selected P3 temporal gate |

Final phase gates and the affected media rerun after the UI hint update passed. The
scripts use ordinary local setup, never provider credentials. The
[completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
owns exact evidence and prerequisites.

### Playback and process recovery gates

The [completed playback/recovery handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records the selected P2-I17/P3-I14 gate commands and exact outcomes.

| Task | Command | Notes |
| --- | --- | --- |
| Run the communication groups | `make p2-communication-check` | Sixteen direct public-API/PostgreSQL groups |
| Run the playback groups | `make p2-playback-check` | Three actual SDK/browser groups in one Playwright case |
| Run the recovery assertions | `make p3-recovery-check` | Seventeen actual process-recovery assertions |

Default M1/P1 startup and the 55-case catalog with 24 registered runners remain
unchanged.

The wrappers require exact closed reports, retained hashes, actual process/backend
ownership, normal and negative/useful-progress paths, and complete cleanup. Safe
diagnostics cannot qualify a failed normal run. Current installed npm/Python
consumers are measured separately. No complete P2/P3 charter row becomes passing
from a task label or mocked media fact. Missing full rows remain non-passing.

### Result receiver gates

| Task | Command | Notes |
| --- | --- | --- |
| Print the receiver schedule | `make p2-result-receiver-plan` | Finite schedule of sixteen storage and four return assertions |
| Run the receiver gate | `make p2-result-receiver-check` | Isolated owner/runtime PostgreSQL profiles, one scheduled receiver-caller kill and actual backup/restore; no room, provider call or carrier send |
| Run the offline archive/installed lane | `make p2-result-receiver-package-plan` and `make p2-result-receiver-package-check` | A separate offline lane |

The offline archive/installed lane covers twenty-five owned groups, eight existing
package assertions and twenty copied fake-port tests. That lane claims zero actual
storage/return assertions. The
[result-delivery work item](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
records prerequisites, exact outcomes, retained failures and full-phase status.

### Original channel-input gates

From the repository root, with the existing local PostgreSQL/API and pinned host
Python/Node toolchain:

```sh
make channel-origin-plan
make channel-origin-unit
make channel-origin-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Print the origin plan | `make channel-origin-plan` | The plan is inert and starts no work |
| Run the origin unit tests | `make channel-origin-unit` | Channel-origin unit tests and P3 channel-policy tests |
| Run the origin source gate | `make channel-origin-check` | Fourteen actual assertions across sixteen owned process groups |
| Check the origin package | `make channel-origin-package-check` | Built and installed public artifacts with explicit fake ports |

The selected source gate passed fourteen actual assertions across sixteen owned
process groups, with complete cleanup.

- It joins native/signed simulated-SMS input to original P1 work, issued policy
  results and the current P2 receipt/read.
- It uses three disposable schemas and one owned post-commit kill of the ACK host.
  The normal application and M1 record remain unchanged.
- Reports use fresh timestamped paths under `.local/validation/p2-channel-origin`.
  Failed runs remain retained.

The separate `make channel-origin-package-check` validates built and installed
public artifacts with explicit fake ports. It does not repeat the actual database
schedule. See the
[origin work item](../docs/work-items/0044-origin-bound-channel-policy.md) for exact
scope, failures and evidence.

Complete joined browser voice/text/SMS and restart/discovery qualification remain
separate. Later [provider journeys and the recorded demo](../docs/work-items/0046-joined-showcase-providers-and-demo.md)
retain their own scope and do not close those gates.

### Workload and document gates

The [completed workload/image handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records passing selected P2-I19/P3-I16 qualification. Run these from the frozen
repository environment:

| Task | Command | Notes |
| --- | --- | --- |
| Inspect the fixed inventories | `make p2-workload-plan` and `make p3-document-plan` | Expose their fixed inventories without starting work |
| Run the P2 workload gate | `make p2-workload-check` | Selects twenty-four local synthetic PostgreSQL/HTTP/workload assertions |
| Run the P3 document gate | `make p3-document-check` | Selects eight contract and twelve actual image socket/lifecycle assertions |
| Repeat from installed artifacts | `make p3-document-package-check` | Repeats those twenty from fresh isolated artifacts after the maintained offline-eight package builder |

The offline-eight package builder is the maintained package builder with eight
offline assertions. None of these commands is a new catalog acceptance runner.

Rules for these gates:

- Preserve each declared aggregate budget across all direct and nested children
  and captures. Workers are threads, not hidden process counts.
- Register every child before fallible post-spawn observation, retain descendant
  groups and wait for actual settlement before dependent deletion.
- Bind the private exact physical-file index, source/archive inputs, independent
  literal oracle and all nested summaries.
- Failure contexts are finite and preserve the first error.
- A diagnostic run, or a missing, skipped, timed-out or incompletely cleaned run,
  never passes.

### Operations and fixed-policy gates

The [operations and policy handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
owns P2-I20/P3-I17. Inspect the plans before the explicit local gates.

| Task | Command | Notes |
| --- | --- | --- |
| Inspect the plans | `make p2-operations-plan` and `make p3-fixed-policy-plan` | Plans start no work and do not constitute qualification |
| Run the operations gate | `make p2-operations-check` | Exercises sixteen real PostgreSQL/HTTP groups and three browser groups in one browser case |
| Run the fixed-policy gate | `make p3-fixed-policy-check` | Runs eight contract and twelve actual HTTP assertions |
| Repeat from installed artifacts | `make p3-fixed-policy-package-check` | Repeats the twenty from fresh isolated public artifacts after a separately counted offline-eight package builder |

Rules for these gates:

- Keep exact role environments, command/capture/proof budgets, actual owner
  barriers, independent factual/durable joins and private physical-file
  inventories.
- The operations UI is a read client, and fixed-policy v2 is standalone HTTP.
- Preserve all 55 catalog definitions and 24 complete registrations. Selected
  slice results cannot register a full P2/P3 row or grant execution/consent
  authority.
- Preserve all predecessor failures. A later explicitly approved resource recovery
  does not rewrite an earlier false cleanup observation.

Results:

- Selected 0040 gates passed, and selected P2-I20/P3-I17 qualification passed.
- The operations report binds all eight complete owner snapshot files through a
  small canonical manifest. It includes each file in its exact direct proof/index
  inventory.
- The original per-file, aggregate, capture, child and deadline budgets remain
  unchanged.
- Current complete registrations remain 24 of 55. Full seventeen-row P2 and
  fourteen-row P3 acceptance remains planned.
- Full P2/P3 and integrated video release checks remain separate.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Catalog metadata | `.venv/bin/python -m harness validate` | Required files, scoped acceptance IDs and runner registrations are valid | Implemented |
| Fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Selected structural groups, the mandatory foundation policy and all implemented Python suites pass | Implemented |
| Documentation checker | `.venv/bin/python -m harness.documentation_check` | The corpus meets the structural documentation rules; not product behavior | Implemented |
| Registered acceptance | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh` | Registered runners pass with fresh evidence; planned rows stay incomplete | Partial: 24 of 55 cases registered |
| PostgreSQL lane | `make postgres-check` | Backend, migration and scope evidence against actual PostgreSQL | Implemented |
| Frontend lane | `make frontend-check` | Frontend checks, tests and builds pass | Implemented |
| Local stack smoke | `python3.14 local-setup/stack.py smoke` | Only its declared transport, readiness and intake checks | Implemented |
| Phase E evidence | `make phase-e-demo` | Exercises five fresh installed runtime containers with two external-commit losses and checked cleanup | Qualified ([work item 0011](../docs/work-items/0011-p1-phase-e-effects-and-completion.md)) |
| Phase F evidence | `make phase-f-demo` | Uses the actual worker profile, preserved synthetic state and installed source hashes | Qualified ([work item 0012](../docs/work-items/0012-p1-phase-f-leases-and-deployment.md)) |

### Outcome semantics

Structural success does not certify product behavior. Missing, skipped and
timed-out requirements remain non-passing:

- Runners must observe a positive test count. Zero tests, required skips, failures
  and timeouts cannot pass.
- Missing implementations produce `not_implemented`, and their group is
  incomplete.

A single run maps its outcome to a harness exit code. A `unittest_discovery`
runner preserves ordinary nonnegative process failures; every other outcome has a
fixed exit code. When the runner exited, its run report also retains the original
runner exit:

| Outcome | Harness exit code |
| --- | --- |
| Passed run | 0 |
| Ordinary nonnegative process failure (`unittest_discovery`) | The runner's own exit code |
| Failed report-kind run | 1 |
| Signal exit | 1 |
| Zero observed unittest tests (`no_tests`) | 1 |
| Launch failure, output limit or invalid runner report (`runner_error`) | 1 |
| Timeout | 124 |
| Required skip or explicit incomplete report (`incomplete`) | 2 |
| No registered runner (`not_implemented`) | 2 |
| Invalid metadata or selection | 2 |

Project and ecosystem aggregates that contain planned rows are incomplete and exit
with code 2. A failure takes precedence: an aggregate exits with code 1 when any
selected run failed, timed out, hit a runner error or observed zero tests. An
aggregate exits with code 0 only when every selected run passed.

The structural checks report their own outcomes:

| Structural report status | Exit code |
| --- | --- |
| `structural_checks_passed` or `documentation_checks_passed` | 0 |
| `failed` | 1 |
| `invalid` (invalid policy, configuration or selection) | 2 |

### Foundation policy and scope selection

- Metadata validation checks required files, scoped acceptance IDs and runner
  registration.
- Foundation policy validates declared ownership, implemented roots, nonempty
  entrypoints and required per-area docs.
- Unknown or duplicate fields, unsafe paths and boundary roots outside their
  declared sources fail closed.
- The mandatory `foundation.json` policy checks services, the console, local setup
  and shared contracts on every selected product scope. Selecting another project
  cannot hide missing entrypoints, a missing policy or forbidden imports. The
  policy creates no additional product acceptance cases.
- Unknown ownership or an unavailable comparison baseline expands affected scope
  conservatively.
- Shared harness, contract or instruction changes require full checks.

### Documentation checker

The docs group runs the documentation checker over the shared corpus that
[documentation.json](documentation.json) declares, including architecture
decisions. It enforces these structural rules:

| Check | Rule |
| --- | --- |
| Corpus | Every required document exists; include patterns add the rest |
| Title | Exactly one H1 |
| Document card | One Field/Value card with six rows in order (Status, Purpose, Audience, Scope, Owns, Related) between the H1 and the first H2; a supported Status value and no empty values |
| Legacy metadata | No `Status:` or `Last reviewed:` lines outside code examples |
| Role sections | Required H2 sections for each role are present and not repeated; design sections are also ordered and nonempty |
| Role tables | Each required-table section for the role contains a populated pipe table |
| Design diagrams | Section-owned, closed, nonempty Mermaid diagrams of the required types |
| Fences | Every fenced code block is closed |
| Links | Markdown links and HTML `src`, `href`, `poster` and `srcset` targets resolve inside the repository |
| Prohibited references | Forbidden terms and source-identifier patterns are absent |

- The [documentation standards](../docs/documentation-standards.md) own the
  sections and tables required for each role.
- Positive and negative fixtures cover each rule, including comments, fenced and
  indented examples, escaped pipes, HTML embeds and invalid policy.
- The checker prints a JSON report with the documents checked and each violation's
  path, line and rule code. Link fragments are not checked.
- Actual Mermaid parsing and semantic design review remain separate from
  structural checks.

### Runner kinds and registration

Register implemented cases in `catalog.json` only after their actual assertions
exist. The three runner kinds use safe relative paths, argument vector (argv)
arrays and explicit deadlines:

| Kind | Mode contract | Maximum catalog deadline |
| --- | --- | --- |
| unittest_discovery | Registered baseline/offline suite metadata | 300 seconds |
| python_json_report | Exact catalog offline/lab/live mode | 300 seconds |
| python_infrastructure_report | Exact catalog lab/live mode; offline rejected | 900 seconds |

- Both report kinds use owned 64 KiB bounded capture and a closed numeric report
  bound to the exact case and mode.
- Raw output and unvalidated reports stay private and are removed. Retained
  diagnostics contain fixed safe codes and counts.
- Product wrappers, not the generic engine, own prerequisites and exact assertion
  mappings.
- Extend runner kinds deliberately, with positive and negative fixtures.
- Do not register placeholder commands as completed behavior.

### Reports and artifacts

Reports under the ignored `.local/harness` directory contain run and scenario IDs,
status, original runner exit, test and skip counts, duration, command and
diagnostic paths. Each run writes its files to a new `.local/harness/<run-id>`
directory:

| File | Contents | Written |
| --- | --- | --- |
| `report.json` | The run report described above | Every run |
| `stdout.txt` and `stderr.txt` | Child output for `unittest_discovery`; report kinds keep only a fixed safe result code | Every run |
| `runner-result.json` | The validated closed runner report | Report-kind runs that return a validated report |

The closed `python_json_report` acceptance protocol remains separate from H1
workload artifacts. Those artifacts already bind mode, canonical manifest, installed
source/image, machine and bounded raw timing/resource records. Media evidence
remains its own lane. See the [validation plan](../docs/validation-plan.md) for
release requirements.

### Root fast-suite execution

The root `tests` directory runs in two fixed, owned Python processes under one
aggregate 120-second deadline.

| Limit | Value |
| --- | --- |
| Aggregate deadline | 120 seconds, including five seconds reserved for cleanup |
| Standard output or standard error | 1 MiB per stream |
| Aggregate capture | 2 MiB |

1. Both processes discover the entire canonical suite independently. They must
   publish identical ordered test IDs before execution is admitted.
2. Three measured SDK-heavy modules form one partition. The other process executes
   the exact complement.
3. Actual started IDs, counts, exit codes and zero required skips must match both
   manifests.

Project and registered acceptance lanes retain their existing runners.

- Root standard output and standard error are private.
- Validated timeout progress contains no raw exception text.
- The retained manifest, result, capture and actual owner records make the
  selection inspectable.
- Ordinary successful fixture cleanup does not establish universal descendant
  containment.
- A forced stop leaves nested cleanup explicitly unverified and cannot pass.

### Frontend, smoke and quality lanes

Frontend verification remains explicit. Run `pnpm check`, `pnpm test` and
`pnpm build` from the root, or `make frontend-check`. Actual local media requires
the setup manager smoke command (`python3.14 local-setup/stack.py smoke`, described
in the [local setup guide](../local-setup/README.md)). Python fast success does not
imply that those lanes ran. Local quality gates include the existing Ruff format
check.

### PostgreSQL lane

The real database gate is `make postgres-check`, run after the documented local
role setup.

- Tests under `tests/postgres` use explicit `pg_*_cases.py` discovery and require
  actual PostgreSQL credentials. They are not silently skipped by the fast lane.
- The lane records its own report under `.local/validation/postgres`, or at the
  explicit `POSTGRES_REPORT` path.
- Its evidence contributes to backend, migration and scope requirements.

### Phase evidence and catalog registration

| Phase | Offline lane discovers | Explicit PostgreSQL lane additionally requires | Demo command | Artifacts |
| --- | --- | --- | --- | --- |
| E (supplier effects and completion) | Mutation data transfer object (DTO), supplier, sink and authenticated effect service tests | v3 upgrade, mutation, effect/outbox and compatibility boundary files | `make phase-e-demo` | `.local/validation/p1-phase-e` |
| F (leases and workers) | Lease DTO and actual owned worker process tests | v4 upgrade, lease and coordination suites | `make phase-f-demo` | `.local/validation/p1-phase-f` |

#### Phase E evidence (supplier effects and completion)

- The explicit PostgreSQL lane's process crashes are actual owned children against
  independent persisted fixtures.
- `make phase-e-demo` exercises five fresh installed runtime containers with two
  external-commit losses and checked cleanup.
- Artifacts remain in `.local/validation/p1-phase-e`, separate from historical
  phase reports.
- Core effect, cancel, event and receiver deduplication records are retained when
  diagnostic projections are pruned.
- A timeout or missing suite never passes.

#### Phase F evidence (leases and workers)

- The PostgreSQL gate's suites include independent workers, stale external calls,
  lock-time expiry, saturation and useful progress.
- `make phase-f-demo` uses the actual worker profile, preserved synthetic state
  and installed source hashes.
- Required setup, zero tests, skips and timeouts fail.
- Private health and metrics snapshots do not replace business outcome and receipt
  records.
- Keep artifacts in `.local/validation/p1-phase-f` and preserve earlier phase
  gates.

Phases F and G additionally contribute lease, worker and local
speech-interruption evidence.

#### Registration rules

- Phase task completion does not register the complete charter requirement.
- The catalog owns current complete registrations. Missing required rows remain
  non-passing.
- Current complete runner registrations remain distinct from granular phase
  completion. Read the catalog instead of inferring coverage from suite totals.
- Exact complete assertion mappings, rather than granular phase counts, govern the
  twenty current P1 registrations.
- No single phase establishes whole-project release.

### Workload evidence boundaries

H1 artifacts live under the ignored `.local/validation/p1-phase-h/<run-id>`
directory, not with the acceptance catalog's `.local/harness` reports.

Observation method:

- The first-result snapshot is validated from submit, replay or GET and is
  source-labelled.
- All HTTP operations share the declared concurrency. Case observation is one
  global round-robin GET followed by a 250 ms sleep, including HTTP/queue lag.
- Resource probes target one second, with actual start, end, duration and skipped
  intervals. They are not guaranteed one-Hz observations.
- Sequential in-container Python probe overhead is included.

Resource interpretation:

- Accounted cgroup memory is not resident set size (RSS) or a peak.
- CPU microsecond counters have explicit first, last, delta and window values. The
  window includes later cancellation/delivery checks.
- Summary statistics are count, minimum, median and maximum. No small-sample tail
  percentile, speech/model metric or production capacity follows.
- The [observability guide](../docs/observability.md) owns detailed
  interpretation.

Failure evidence:

- Original failures retain fixed-enum operation/code and observed bounded process
  exit/timeout/budget/elapsed metadata before temporary capture removal. Cleanup
  failures remain separate.
- Raw command, output, environment, body and exception text is excluded.
- Automatic host/runtime metadata does not include Docker virtual machine (VM)
  hardware. Separately collected operator environment evidence must be labelled
  accordingly.

Pass rules:

- Missing setup, progress or observations, an unknown unresolved acknowledgement,
  an exceeded deadline or failed owned cleanup remains non-passing.
- A pre-cleanup measurement snapshot is not a phase pass.
- Preserve safe failed evidence and closed Phase G artifacts.
- Do not convert this H1 contribution into a complete acceptance runner or release
  claim.

## Next milestone

P1 V1 is qualified for the local POC using provider_real v2. local_real remains
unqualified. Phase H2 restart, slow-dependency, saturation and shutdown
measurements passed. P1-I26 host/Linux isolated artifacts, independent API/failure
review and the genuine native consumer also passed. The
[Phase H release-qualification work item](../docs/work-items/0019-p1-phase-h-release-qualification.md)
records the local P1 V1 qualification.

Later work follows the [build plan](../docs/build-plan.md). Meanwhile:

| Step | Outcome | Gate |
| --- | --- | --- |
| Keep the independent inquiry-worker crash scenarios passing | Stays passing and preserved | [Phase B work item](../docs/work-items/0008-p1-phase-b-inquiry-recovery.md) |
| Keep the explicit PostgreSQL cutover/parity lane passing | Stays passing and preserved | [Phase C work item](../docs/work-items/0009-p1-phase-c-postgres-cutover.md) and the [PostgreSQL lane](#postgresql-lane) |
| Keep the Phase G native/media/trace gate passing | Stays passing and preserved | `make phase-g-demo` |
| Retain the S-I06/P1-I27 inquiry baseline qualified locally | Stays retained and reproducible | [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md) |
| Keep BASE-01 and the selected P3-01/P3-03/P3-11 lab assertions passing | Stays passing and preserved | Their registered runners; see [Selected P3 lab cases](#selected-p3-lab-cases) |
| Preserve historical source-bound evidence | Stays preserved | Retained work-item evidence |
| Retain planned status for all 17 P2 rows and the remaining 14 P3 rows | Aggregates stay incomplete | Deep lane exit code 2 |
| Retain unqualified status for local_real | No local_real qualification claim | Its own fresh evidence must pass first |
| Pursue full P2/P3 acceptance and joined voice/text/SMS qualification | Recorded provider journeys/video do not close complete gates | Its own separate gate |
