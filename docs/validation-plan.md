# Portfolio validation and release evidence

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define what counts as validation evidence and record the gates for each phase and selected checkpoint |
| Audience | Engineers and coding agents who plan, run or review validation work |
| Scope | Test lanes, engineering and release gates, fault rules, load methodology and evidence; excludes requirements and setup commands |
| Owns | Test lanes, required fault scenarios, benchmarks and evidence |
| Related | [Portfolio scope](portfolio-scope.md) · [Python engineering](python-engineering.md) · [Technology baseline](technology-baseline.md) · [Harness guide](../harness/README.md) · [Work item template](work-items/template.md) |

## Overview

This plan defines what counts as validation evidence for the three projects. It
covers test lanes, engineering gates, deterministic scenario and fault rules, load
methodology, evidence reporting and release gates. It also records the gate
requirements and results for each P1 phase and each selected P2/P3 checkpoint.

| Section | What it covers |
| --- | --- |
| [Test lanes](#test-lanes) | Which lane to run for each kind of change |
| [Engineering gates and acceptance authoring](#engineering-gates-and-acceptance-authoring) | The G-READY to G-RELEASE gates, acceptance criteria fields and diagnostic tests |
| [Deterministic scenario protocol](#deterministic-scenario-protocol) and [required fault boundaries](#required-fault-boundaries) | How scenarios, schedules and fault injections are built |
| [Replay retention and remote trust](#replay-retention-and-remote-trust) | Replay horizons and P3 remote invocation |
| [Load methodology](#load-methodology) | Workload experiments, measurements and budgets |
| [Evidence and reporting](#evidence-and-reporting) | Run records, artifact storage and LiveKit test tools |
| [Development workflow for people and coding agents](#development-workflow-for-people-and-coding-agents) and [release gate](#release-gate) | The slice workflow and the V1 release gates |
| [Audit-driven integration and operational qualification](#audit-driven-integration-and-operational-qualification) | Future exit criteria, test discovery, consumer feedback and dependency scanning |
| [Foundation commands and qualification](#foundation-commands-and-qualification) | Current commands and foundation evidence |
| [P1 phase gates](#p1-phase-gates) | Phase A to Phase H gates and the current P1 qualification |
| [P2 and P3 lanes and selected checkpoints](#p2-and-p3-lanes-and-selected-checkpoints) | Contract lanes and selected checkpoints through native policy, result return and original-input binding |

### Delivery scope

The current user-approved delivery is a fully local proof of concept (POC).
GitHub publishing and remote continuous integration (CI) execution are out of
scope. Existing CI configuration is optional reference material. Execute the
local checks and the actual store, process, container, artifact, browser and
inference gates below. Hosted execution is not required before finishing P1 or
starting P2 under this delivery scope.

### Traceability

Every project has a finite V1 scope in [portfolio-scope.md](portfolio-scope.md).
Use the acceptance IDs in the three project charters as the traceability unit.
The harness discovers those IDs and records executable evidence as scenarios are
implemented. A documented requirement, a mocked fixture or a green unrelated test
is not evidence that a product scenario works.

### Terms

| Term | Meaning |
| --- | --- |
| P1, P2 and P3 | The Agent Continuity Lab, Channel Continuity Kit and Delegation Reliability Kit projects |
| M1 | The original SQLite confirmed-investigation intake |
| Acceptance ID, such as P1-05 | A charter row |
| Implementation task ID, such as P2-I15 | A roadmap task |
| Compressed list, such as P2-I04/I10/I11 | P2-I04, P2-I10 and P2-I11 |
| Four-digit number, such as 0036 | A work item under `docs/work-items` |
| Selected qualification | The gates chosen for one work item passed within that item's declared local scope; it never completes a full acceptance row by itself |
| offline, lab and live | The execution modes defined in the [portfolio scope](portfolio-scope.md) |
| scripted, local_real and provider_real | The trusted inference modes; scripted is the default |
| ACK | Acknowledgement |
| CAS | Compare-and-set |
| DDL | Data definition language |
| HMAC | Hash-based message authentication code |
| OTLP | OpenTelemetry Protocol |
| PID | Process ID |
| RSS | Resident set size |
| RTC | Real-time communication |
| SFU | Selective forwarding unit, the self-hosted LiveKit media server |

### Current status

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 | Qualified locally with selected provider_real v2 | [Current local P1 qualification](#current-local-p1-qualification) |
| local_real profile | Not qualified | [Current local P1 qualification](#current-local-p1-qualification) |
| Harness catalog | Partial: 24 of 55 cases registered | [Catalog registrations](#catalog-registrations) |
| Selected P2/P3 checkpoints | Qualified within their own gates | [P2 and P3 lanes and selected checkpoints](#p2-and-p3-lanes-and-selected-checkpoints) |
| Complete P2/P3 acceptance and integrated release | Planned | [Catalog registrations](#catalog-registrations) |

The 24 registered cases are BASE-01, all twenty P1 rows, and P3-01, P3-03 and
P3-11. Seventeen P2 and fourteen P3 rows remain planned.

## Test lanes

| Lane | Run when | Required evidence |
| --- | --- | --- |
| Baseline | Every change to the existing starter or harness | Existing intake tests; harness validation and runner tests |
| Deterministic correctness | Every affected implementation slice | Exact invariants, schema errors, replay/conflict, transitions, fake-clock expiry and bounded cancellation |
| Persistence and processes | Changes to storage, worker or delivery behavior | Actual database, independent processes, failpoint-controlled termination and recovery |
| Cross-language contracts | Changes to Python/TypeScript messages | Shared versioned fixtures accepted/rejected consistently, including unknown version and scope errors |
| Local media | Changes to agent, browser, modality or reconnect behavior | Actual self-hosted LiveKit, browser/SDK observations and audio fixtures; no external AI needed |
| Live inference | Before claims about voice/vision/model behavior and portfolio release | Selected real-model runs, checked task outcomes, configuration, costs and artifacts |
| Load and regressions | First baseline, milestone releases or performance changes | Bounded steady/burst/saturation tests, raw samples and comparison to recorded baseline |

Lane rules:

- Keep default local checks independent of provider credentials.
- Missing mandatory setup or scenarios makes a gate incomplete. It cannot silently
  become a skip or a pass.
- Optional live lanes report "not run" when credentials are unavailable. Such a
  run cannot support live-quality claims.
- Cloud simulations are optional and separate.

## Engineering gates and acceptance authoring

### Engineering gates

The gates below are engineering checkpoint names, not new acceptance or catalog
IDs. Select the applicable gates in each implementation work item before coding.

- A gate with a required but unavailable prerequisite remains incomplete for that
  feature. Independent offline work can continue.
- The current commands do not yet implement every future runner listed in the
  product plans.

| Gate | Applies when | Required assertions and evidence |
| --- | --- | --- |
| G-READY | Every substantial slice | Existing task/acceptance IDs, Given/When/Then criteria, authority/commitment boundary, migration/configuration impact, ordinary/fault schedule, test mode and resource/time budget reviewed |
| G-FAST | Every source/shared policy change | Existing full fast Python/static/docs/type checks and format check pass; affected TypeScript check/test/build passes; new source is included in discovery and typing |
| G-CONTRACT | Public API/schema/adapter changes | Producer/consumer positive and negative fixtures agree on versions, bytes/units, trusted scope, semantic replay/conflict and safe typed errors; no public source-internal imports |
| G-DURABLE | Persisted work/effects/delivery | Actual supported store, concurrent schedules, commit-response-loss, real child termination/restart, preserved identity, migration/restore and eventual useful progress; provider ledger independent of killed worker |
| G-OBS | New event/error/metric/export boundary | Inspect real emitted fields and counter/timing changes; sentinel secrets absent from response/log/trace; finite dimensions, no duplicate events/handlers or cross-context leakage; telemetry failure remains bounded |
| G-MEDIA | Agent/browser/modality/route lifecycle | Actual self-hosted browser/SDK path, track/sender correlation, permission-denial/cleanup, interruption and required playback/reconnect/return-route observations; emission/text simulation is insufficient |
| G-PACKAGE | New package consumer/release | Isolated built wheel/npm-pack installation, real minimal public example, declared dependencies/exports and advertised runtime support evidence; no repository path injection |
| G-RELEASE | Local or portfolio release | All applicable acceptance modes, independent API/failure review, measured workload budgets, supported-platform/setup/restart/shutdown and short success/failure demos; portfolio adds selected real-inference outcomes/configuration/cost |

### Code quality expectations

The [Python guide](python-engineering.md) defines typing, task and resource
ownership, transaction, exception and diagnostic practices.

- Existing lint and type coverage is scoped. New packages enter those checks as
  they are introduced.
- There is no universal arbitrary line-coverage threshold. Inspect critical
  transitions and failure paths.
- Targeted mutation testing is useful only when a concrete invariant justifies it,
  not as another framework prerequisite.

### Acceptance criteria fields

Write each acceptance criterion with these fields:

| Acceptance field | Required content |
| --- | --- |
| Traceability | Existing requirement and task IDs, owner and authoritative contract |
| Given | Trusted principal/scope, persisted state/revision, dependency capability and fixture seed |
| When | Public action and deterministic race/crash/failure point; actual process boundary where claimed |
| Then: safety | Exact store/effect/route state, forbidden side effects and stable identity/canonical payload |
| Then: liveness | Expected eligible work/result progresses; rejecting all work cannot pass |
| Diagnostics | Stable safe code, retry/reconciliation meaning, expected producer event/metric and redaction assertions |
| Execution | Offline/media/live lane, real versus fake adapters, timeout, resource limits, cleanup and artifact paths |
| Completion | Nonzero executed assertions, no required skip/timeout, inspected outcome and remaining partial assertions identified |

### Example acceptance contracts

The P1-05 contract below has actual SQLite process evidence. The P2-03 and P3-05
examples describe required future complete assertions. Partial slice evidence or
wording alone never establishes acceptance.

- **P1-05:** given an independently persisted supplier inquiry and original
  accepted identity, kill the worker after supplier success but before local
  acknowledgement. A fresh worker reconciles that inquiry, preserves payload and
  effect identity, completes the eligible request and makes zero booking
  mutations.
- **P2-03:** given input committed before dispatch, kill and restart the gateway.
  The original receipt is inspectable, dispatch resumes under its original
  operation key, and the case makes useful progress without another business
  acceptance.
- **P3-05:** hold result A, accept revision B, then release A and complete B. A
  stays historical and causes zero current action intents, while a valid confirmed
  B can progress through the real case authority.

### Diagnostic tests

Diagnostic test inputs include:

- provider and storage exceptions containing sentinel secrets;
- unknown input fields;
- request and room IDs;
- credentials and raw URLs.

Assert that these values are absent from public diagnostics, while the safe code
and useful correlation remain. Exercise expected failures, unexpected
outer-boundary defects, cancellation and collector outages separately. Investigate
leaked resources and unretrieved task exceptions. Do not hide them with warning
suppression.

## Deterministic scenario protocol

### Scenario definition

Each scenario defines an ID, project, requirement, mode, fixtures, preconditions,
process boundaries, actions, exact assertions, timeout, cleanup and artifacts.

- An implemented registration points to a known executable runner.
- A planned scenario has no executable. It returns not_implemented with a nonzero
  exit status.

### Schedules, clocks and process crashes

- Use barriers or failpoints for concurrency schedules.
- Use a controllable clock for timers and retry eligibility. Do not depend on long
  sleeps or lucky races.
- Fake provider state must survive the worker crash independently of the worker's
  local acknowledgement.
- Process termination must actually terminate the process in the crash test.
  Reopening a connection is insufficient evidence of process recovery.

### Failure injection

For each failure injection, include a normal path and a recovery or liveness
assertion. Rejecting all work must not pass safety tests. Compare final database,
supplier and delivery observations against expected histories.

## Required fault boundaries

Each boundary below needs its listed assertions, in addition to the normal-path
and recovery assertions that every failure injection requires.

| Boundary | Required assertions |
| --- | --- |
| Before intake commit | No accepted acknowledgement; no partial accepted record |
| After commit before response | Retry returns the original identity and payload |
| After supplier effect before local acknowledgement | Reconcile under supplier contract; uncertain outcome when safe evidence is absent |
| Lease expires while an old worker resumes | Reject stale state write; separately test the external request boundary |
| Completion committed before outbox delivery | Recover a stable logical event and deduplicate at a cooperating receiver |
| Message persisted before agent dispatch | Recover accepted input after gateway/process failure |
| Outbound send succeeds but acknowledgement is lost | Preserve stable identity and explicit uncertainty without unsupported one-SMS claims |
| User revision races with specialist result | Atomic case-authority decision; no action based on stale/unauthorized input |
| Revision or cancellation after intent commitment | Respect the documented best-effort external boundary; expose actual outcome |
| Room reconnect or agent handoff | Load the right scoped case and current route; preserve partial/unknown communication evidence |
| Slow storage, supplier, carrier or specialist | Bound concurrency and queues; keep active conversation responsive and admitted work inspectable |

## Replay retention and remote trust

### Replay horizons before cleanup

Before automated cleanup, record the supported replay horizon, the retained
idempotency and effect tombstones, and the behavior after identity expiry.

- Pruning display history or passing a business deadline cannot make an already
  accepted logical operation new again.
- Test a delayed replay after history pruning. Preserve the uncertainty and effect
  evidence required for reconciliation.

### Remote specialist trust

For P3 HTTP invocation, bind scope to an authenticated local service principal.
Authorize invocation, status and result queries, cancellation and image access.

- Test forged body scope, unavailable or invalid service credentials and
  cross-tenant references.
- P1 owns durable attempts and retry and deadline eligibility. Remote status,
  cancel acknowledgement and late results are correlated observations.
- Test lost responses and duplicate invocations without creating another
  recovering queue.

### Specialist baseline

Before independent specialist implementation, retain a controlled tools/native
subagent baseline and deployment decision. Work package PLAN-21 still runs the
final three-way comparison, with equivalent model and provider configuration where
applicable.

## Load methodology

Measure infrastructure and real media separately. Begin with deterministic
workloads, then use small real-model and media runs within declared resource and
provider limits. V1 requires a laptop-local capacity study, not a claim of
production or global scale.

### Workload design

Suggested starting experiment points:

| Experiment dimension | Suggested starting points |
| --- | --- |
| Concurrently active fake jobs | 1, 10 and 50 |
| Independent workers | 1 and 2 |
| Dormant conversation records | 1,000 |

- Use fixed seeded workloads and publish the seed.
- Increase load only while local resources stay within configured bounds.
- These points are experiments, not promised capacity or minimum throughput.
- For real audio, establish one correct session before increasing load.

### Required experiments

Required experiments are steady load, a bounded burst, sustained saturation,
worker termination and restart, and a slow-provider case.

- Include a second admitted tenant when testing per-tenant caps.
- Overload must reject or defer explicitly before acceptance, or preserve accepted
  work under its documented policy.

### Measurements to record

| Area | Measurements |
| --- | --- |
| Outcomes | Accepted, completed, failed and uncertain counts |
| Correctness | Lost accepted work and duplicate external effects |
| Latency and lag | Queue age, recovery lag, admission and dispatch latency, and event-loop lag |
| Resources and errors | CPU, measured memory with its accounting basis, and errors |

- For delegation, assert zero stale action intents and successful progression of
  expected current results.
- Keep filler responses separate from useful task progress.

### Voice and SDK telemetry

For voice, record the time from speech end to first audible response, the first
meaningful response, interruption yield and the time to a useful result.

- Mark timestamp sources. Agent-side emission and client-side playback
  observations are different.
- Collect the installed SDK's current chat-message and provider metrics, session
  usage and session reports through documented supported hooks
  ([LiveKit data hooks](https://docs.livekit.io/testing/observability/data/)).
  Use bounded OpenTelemetry export where applicable.
- Establish the hook and version contract at integration. The deprecated
  session-level metrics_collected is not the target API.
- Inject exporter, provider and store failures. Assert safe classified outcomes,
  and prove that telemetry failure does not block conversation or create unbounded
  retries.
- Report sample counts with every latency summary. Show p50/p95 or other
  percentiles only with enough samples to interpret them; small runs can retain
  minimum, median and maximum instead.
- Stage timings differ by pipeline. Do not invent speech-to-text (STT), large
  language model (LLM) or text-to-speech (TTS) timings for a model that does not
  expose them.

### Budgets and baselines

Before performance-sensitive implementation, retain a baseline using the selected
stack and machine. Set numeric budgets in the workload manifest before evaluating
the change.

- If behavior exceeds a budget, investigate and fix it, or document a reviewed
  tradeoff and update the baseline explicitly.
- Never rewrite expected results just to turn a failed run green.

The Phase H1 declared inquiry baseline, under P1 phase gates, applies this
methodology to the P1 inquiry workload.

## Evidence and reporting

### Run records

Each run records:

- schema version, run and scenario IDs, result and mode;
- code snapshot provenance, stack versions and fixture seed;
- workload and resource limits and timing sources;
- commands, elapsed duration and relevant artifact paths.

Live runs additionally record the model, provider and configuration, the region
where known, sample count, task outcomes, and cost or an explicit unavailable-cost
observation. Never dump credentials or the entire process environment into a
report.

### Artifact storage and correlation

- Write disposable run output under the ignored .local/harness directory.
- Promote reviewed, sanitized summaries and reproducible fixtures to a versioned
  evidence directory when a release needs them.
- Logs and traces must correlate case, revision, workflow, delegation, attempt,
  effect and delivery identities without treating correlation as authorization.
- Preserve the raw results needed to explain a failure.

### LiveKit test tools

LiveKit [unit tests](https://docs.livekit.io/testing/unit-tests/) support turn,
tool and handoff assertions. Cloud
[Agent Simulations](https://docs.livekit.io/testing/simulations/) can supplement
conversation evaluations, but text mode bypasses audio. The local gate must not
depend on Cloud or infer actual playback behavior from text tests.

## Development workflow for people and coding agents

1. Read the root and nearest AGENTS.md, the affected Design.md, the charter and
   the current implementation status. Select the acceptance IDs for the change.
2. Write a short change plan with behavior, interfaces, failure cases, validation
   commands and scope limits. Existing deterministic contracts govern the plan.
3. Implement one coherent slice with typed boundaries and meaningful tests of the
   relevant failure behavior. Add new schema migrations without dropping existing
   data. Avoid unrelated refactors.
4. Run the narrow checks, then the required integration lane. Run lint, type and
   build checks for affected languages once those toolchains exist. An unavailable
   tool is a reported gap, not a pass.
5. Inspect artifacts. Review correctness, cancellation, resources, schema
   compatibility, API ergonomics and documentation against the acceptance IDs.
6. Update implementation status, decisions and evidence. Record AI assistance and
   leave a concise handoff with commands, results and unresolved work.

### Learning and authorship

The learning workflow remains explain, attempt, review, change. AI assistance does
not remove the need to understand and modify the implementation. Scope and
harness work can be assisted, but portfolio authorship claims must match
contributions.

## Release gate

### Local-ready and Portfolio-ready V1

| Gate | Requires |
| --- | --- |
| Local-ready V1 | All applicable deterministic and local-media acceptance rows, standalone examples, integrated contract checks, clean setup, migrations, restart, bounded shutdown and local load evidence |
| Portfolio-ready V1 | Local-ready V1 plus selected real-model behavior, benchmark comparisons, a usable minimal API, documentation review and a short success/failure demonstration |

Each gate reports passed, failed and unimplemented IDs explicitly. The
[portfolio scope](portfolio-scope.md) defines both release gates.

### Independent review

Require an independent review of the public API and failure contract. The review
must identify assumptions, try the documented setup and verify at least one
failure scenario. Resolve actionable findings, or retain a justified and scoped
limitation, before release. Percentage coverage alone is not a release criterion.

## Audit-driven integration and operational qualification

The [audit disposition](work-items/0020-architecture-audit-reconciliation.md) maps
the original architecture findings to evidence and owned follow-ups. Later
reviews retain their own records in the [checkpoint history](checkpoint-history.md).

### Review-driven exit criteria

The rows below remain required exit criteria for their affected boundaries.
Selected slices have since passed gates recorded below; broader assertions remain
open. This table is not a passing registration or an addition to the 55-case
catalog. Preserve existing project acceptance IDs.

| Owner and existing mapping | Deterministic negative schedule | Useful-progress and evidence requirement |
| --- | --- | --- |
| P2-I03 / P2-12 | Expired/replayed/concurrently consumed association challenge; revoked or reassigned number; valid webhook with another account's case | Current verified association succeeds; no cross-account read/send; actual persisted association/version and protected access checks |
| P2-I04/I10/I11 / P2-05/06 | Skewed/delayed provider timestamps and simultaneous channels; stale or unlinked confirmation | Persist server acceptance order in its named namespace; current exact revision/confirmation progresses; no timestamp-derived authority |
| P2-I12/I13/I18 / P2-09/10/12 | Hold delivery, replace room/route, revoke association, then replay old callback; lose send acknowledgement | Same immutable recipient and logical send identity; current verified route progresses; original ambiguous send stays unknown and retains provider idempotency key where supported |
| P3-I03/I04/I16/I17 / P3-11/15 | Schema-valid wrong fixture fact, altered or cross-account source, invented evidence/rule, injected screenshot instructions | Exact accepted input/source binding, bounded authorized evidence and factual evaluation; ambiguity requests clarification, grounded current facts progress |
| P3-I12 / P3-06/07 | Evaluate A, prepare intent, commit B in another transaction, then submit A; run inverse ordering too | Actual PostgreSQL barriers: zero stale A intents/effects, valid independently confirmed B commits once; postcommit outcome remains explicit |
| S-I08 / integrated release | Cross-account callbacks/results, authorization changes at commitment, malicious input, slow dependency plus valid burst | No capability escalation, bounded queues/tasks, useful valid progress and inspected real sanitized exports; no placeholder metrics |
| Planned P1 operational follow-up | Restore before reservation and before intent while independent supplier/receiver advance; crash reconciliation; race reviewers | Dispatch quarantine, no duplicate mutation, original identities where provable, append-only observations and separate consent; see the [operational work item](work-items/0021-p1-operational-safety-extensions.md) for exact safety/liveness criteria |

### Implementing these criteria

- A documentation check verifies contracts and links, not these product behaviors.
- Before each implementation, freeze the actual schemas, finite time and resource
  budgets, failpoints, error vocabulary and evidence destinations in its work
  item.
- Run the real store, process or media lane when that boundary is claimed.
- Do not invent a passing runner for future adjudication, restoration, P2 or P3
  work.

### Test discovery for new packages

| Task | Command | Notes |
| --- | --- | --- |
| Run the root suite and all three project Python unittest suites | `make test` | None |
| Run those suites plus the fail-closed structural and test harness, Ruff and maintained typing | `make check` | None |
| Check formatting | `make format-check` | Remains a separate gate |

pytest is installed tooling, not a second claimed correctness lane.

When a P2 or P3 package first has source, add its actual workspace and member
paths, lint, format and type checks, tests and build commands in the same slice.
Prove with a failing package fixture and a nonzero test count that the root gate
executes it. A console-only pass cannot qualify a new package.

### Human consumer feedback

The G-PACKAGE gate proves artifact execution. It does not prove first-time human
usability. Follow [CONTRIBUTING.md](../CONTRIBUTING.md) for a fresh consumer
feedback record:

- freeze the runtime and artifact;
- time the setup;
- record missing steps and actionable error interpretation;
- retain the resulting API or documentation revision, or the reason for keeping
  the API.

Human feedback remains pending until a person actually supplies it. Automated
independent review must retain its own attribution.

### Dependency inventory and scanning

Dependency inventory and scanning is a separately planned local tooling gate in
the [technology policy](technology-baseline.md#dependency-inventory-tool-qualification).
A lockfile or successful frozen installation is not a completed vulnerability
scan.

## Foundation commands and qualification

### Current foundation commands

Run these from the repository root:

| Task | Command | Notes |
| --- | --- | --- |
| Run documentation and module checks, all implemented Python tests, and maintained Python lint and service/core type checks | `make check` | Runs in the frozen environment |
| Check, test and build the four workspace TypeScript packages | `pnpm check`, `pnpm test` and `pnpm build` | Covers the console, the P2 channel-continuity package, the P3 delegation specialist and the channel-policy gateway |
| Exercise actual API readiness, local authentication, M1 replay and conflict, named-agent dispatch, text and fixture audio | `python3.14 local-setup/stack.py smoke` | The local-setup manager's smoke command; see the [local setup guide](../local-setup/README.md) |

These commands are separate from product acceptance.

### Catalog registrations

| Catalog rows | Status | Evidence |
| --- | --- | --- |
| All twenty P1 rows | Runners registered with retained passing reports | [Phase H assessment](work-items/0019-p1-phase-h-release-qualification.md) |
| P3-01, P3-03 and P3-11 | Complete registered lab runners with retained passing reports | [Revision routing and complete P3 lab acceptance](#revision-routing-and-complete-p3-lab-acceptance-0031) |
| All 17 P2 rows | Planned | Not applicable |
| The remaining 14 P3 rows | Planned | Not applicable |

The Phase H assessment owns the qualified P1 scope and provenance limits.

### Foundation and media evidence

| Check or capability | Result | Source |
| --- | --- | --- |
| Native SDK smoke from the host and from a container on macOS arm64 Docker Desktop | Passed | [Foundation work item](work-items/0003-local-project-foundation.md) |
| Authenticated browser room and text, explicit disconnect and reconnect, and M1 acceptance, replay and conflict | Passed | [Foundation work item](work-items/0003-local-project-foundation.md) |
| Actual scripted WebAudio/WebRTC input, returned browser audio, active interruption, fresh-room same-task continuation, held-dependency controls and inspected filtered traces | Added by the separate Phase G gate | [Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| Actual provider recognition, tools, synthesis and browser playback | Established in its declared local scope by the separate selected provider_real v2 gate | [Provider operations guide](provider-demo.md) |
| Physical microphone quality, automatic network-loss media recovery, local_real qualification and production capacity | Unqualified | Not applicable |
| Remote CI | Outside scope | Not applicable |

A normal stop and start must preserve the M1 identity without a volume reset.
Optional Jaeger UI readiness alone does not establish exported traces. See the
[foundation work item](work-items/0003-local-project-foundation.md) for results
and the [local setup guide](../local-setup/README.md) for operational commands.

### Browser foundation checks

Before broad product feature expansion, exercise these checks in the actual
browser:

- the authenticated local connection and invalid credentials;
- text echo and expected-agent sender checks;
- exact diagnostic payload handling;
- disconnect and reconnect.

Test explicit microphone enablement and permission denial where browser
automation permits it. Use deterministic audio fixtures for repeatable media
assertions, and correlate frame reports to the intended track. Report
capability-blocked browser checks as pending.

Host and container SDK smoke and browser playback remain distinct evidence.
Qualify the supported local host and Linux-container paths with actual installed
execution, not source imports or workflow YAML. Hosted CI and publishing are
outside this POC scope. These are foundation checks, not completed product IDs.

### Installed package consumers

P1 has a standalone src-layout distribution and real isolated consumers:

1. Build its wheel and source distribution (sdist).
2. Rebuild from the sdist.
3. Install outside repository import paths.

P2/P3 selected installed consumers are recorded in
[0038](work-items/0038-case-rehydration-and-standalone-release.md) and
[0041](work-items/0041-standalone-channel-and-durable-policy.md). Apply the same
artifact discipline to later changes and release. A distribution's minimal
public-API example must work using declared dependencies
and exports, with no hidden sibling source imports. An installed P1
execution-library dependency may support P3 standalone use without requiring the
full P1 service deployment. Repeat the applicable consumer test in the release
lane.

## P1 phase gates

These gates record the requirements for each P1 implementation phase, in delivery
order. The subsections below hold each gate's full assertions.

| Phase | Gate | Required lanes and commands | Work item |
| --- | --- | --- | --- |
| A and B | Execution evidence for P1-01 to P1-05 | Shared five-test `test_execution_acceptance.py` suite; four-test independent inquiry/supplier crash suite | [Phase A](work-items/0007-p1-phase-a-execution-foundation.md) · [Phase B](work-items/0008-p1-phase-b-inquiry-recovery.md) |
| C | PostgreSQL gate | `local-setup/stack.py` setup, then `make postgres-check` | [Phase C](work-items/0009-p1-phase-c-postgres-cutover.md) |
| D | Authority and continuation | PostgreSQL gate with the v2 upgrade; `make phase-d-demo` | [Phase D](work-items/0010-p1-phase-d-authority-and-waits.md) |
| E | Mutation, cancellation and completion | Full fast lane; `make postgres-check` with `POSTGRES_REPORT`; `make phase-e-demo` | [Phase E](work-items/0011-p1-phase-e-effects-and-completion.md) |
| F | Lease, admission and bounded deployment | PostgreSQL lane with the v4 upgrade, lease and coordination suites; `make phase-f-demo` | [Phase F](work-items/0012-p1-phase-f-leases-and-deployment.md) |
| G | Conversation and media | Offline discovery, PostgreSQL and installed stack lanes | [Phase G](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| H1 | Declared inquiry baseline | `make p1-benchmark-plan`; `make p1-benchmark` | [H1](work-items/0014-p1-phase-h-workload-baseline.md) |

### Phase A and Phase B execution evidence

P1-01, P1-02 and P1-03 use the shared five-test test_execution_acceptance.py
suite. It covers actual owned accepting-process termination,
commit-before-acknowledgement barriers, six concurrent acceptors and scoped replay
and conflict.

- Migration tests additionally exercise old data, abrupt precommit exit and SQLite
  backup and restore.
- Async tests use actual thread barriers.
- Phase B provides the four-test independent inquiry/supplier crash suite for
  P1-04 and P1-05.
- Phase C adds a separate required real-PostgreSQL lane. Richer lifecycle and
  media evidence remain separate.

See the [phase work item](work-items/0007-p1-phase-a-execution-foundation.md).

### Phase C PostgreSQL gate

Run the lane in this order:

1. Run init, start, prepare-postgres and migrate-postgres through
   local-setup/stack.py.
2. Run make postgres-check using the frozen project interpreter.

This explicit lane loads private local credentials without printing them, rejects
ambient target redirection, and creates and removes only isolated owned schemas.

- Missing setup, connection refusal, zero tests and skips cannot pass.
- Fast tests do not silently start Docker and do not substitute for this lane.
- The optional example CI workflow includes this lane. Remote CI execution is
  outside the local POC scope and is not a release prerequisite.

Required assertions:

- exact M1 and inquiry import, and backed-up source quiescence;
- precommit rollback and abrupt migrator loss at recorded checkpoints;
- idempotent completed receipts after legitimate target progress;
- final locked activation verification;
- role, DDL and control-write rejection;
- common SQLite and PostgreSQL behavior;
- trusted actor cross-scope denial;
- normal inquiry, and independent-process supplier success before local
  acknowledgement.

Preserve the first SQLite proof. When this gate was defined, full P1-15 leases and
P1-17 signals and cancellation remained non-passing until implemented. Both rows
now have registered runners with retained passing reports.

### Phase D authority and continuation gate

The PostgreSQL gate also requires the v2 upgrade and the exact authority and
wait/signal/retry suites. It tests:

- current scope, actor, revision, quote and deadline;
- known-receipt replay after expiry;
- revision-versus-commit winners and atomic intent and event;
- stale-wait invalidation and fresh revision progress;
- finite transient retry, and permanent, exhausted and deadline failure;
- ambiguity without resend;
- independent process restart.

Required suite files, zero-test discovery and skips fail closed.

make phase-d-demo uses two distinct runtime-only containers with no shared
application files:

1. Before the first container exits, assert pending waits and no intent.
2. In the next container, observe exact consumption, stable replay, a separately
   expired wait, an unchanged supplier, positive metric samples and safe JSON
   events.

The artifact passes only after owned schema and container cleanup succeeds.
Existing M1 data and volumes and the real RTC smoke must still pass. This is not
browser, human-presence or model evidence.

The default PostgreSQL report is .local/validation/postgres/latest.json. An
explicit POSTGRES_REPORT selects a phase artifact without overwriting historical
gates.

### Phase E mutation, cancellation and completion gate

Run the lanes in this order:

1. Run the full fast lane, strict changed-boundary types and the format check.
2. Run make postgres-check with POSTGRES_REPORT under .local/validation/p1-phase-e.

The real database lane requires the v3 upgrades, the mutation worker, the effect
and outbox suites, and the Phase E compatibility and cancellation boundary suites.
No required suite can be removed, silently skipped or replaced by mocks. Keep
database checks serial with image builds, and keep the existing finite lock and
connection deadlines.

#### Mutation and cancellation assertions

- exact v2 case, provider and expected-revision consent;
- literal v1 preservation and known receipt replay, without granting legacy
  mutation;
- wrong provider before the attempt budget;
- normal authorized progress;
- actual kill and abrupt exit after supplier commit;
- cooperating deduplication and lookup, and genuine noncooperating uncertainty;
- precommit, pre-dispatch and possible-dispatch cancellation races, and immutable
  terminal truth.

Corrupted active-attempt evidence must fail closed without closing another
workflow's attempt. Scope and owner checks precede replay, and external calls
occur outside protected transactions. Replacing a pending quote withdraws its old
wait without extending the original business deadline.

#### Completion and delivery assertions

- terminal outcome, event and pending-delivery atomicity;
- rollback at insertion barriers;
- actual receiver commit before process loss, and fixed receiver identity;
- finite backoff and exhaustion with the business result preserved;
- altered replay rejection;
- late deduplication after diagnostic pruning.

Core receipts remain retained at capacity.

#### Installed demo and scope

After an image rebuild, make phase-e-demo must observe two external-commit crashes
and recovery in fresh installed containers, with source hashes, real safe events,
positive metrics and owned cleanup. Then run the existing RTC smoke to preserve
native text and audio and the original M1 identity.

These lanes contribute to P1-06, P1-07, P1-08, P1-09, P1-13, P1-14 and P1-16, and
to migration and retention requirements. They do not complete the
speech-interruption, lease, browser, model, full platform or portfolio release
gates. The harness catalog owns current complete registrations, and missing rows
remain non-passing.

### Phase F lease, admission and bounded deployment gate

Require the previous Phase E gate, an explicit owner-only ACTIVE v3-to-v4 upgrade,
and the current frozen dependency and image baseline. The PostgreSQL lane
additionally requires pg_upgrade_v4_cases.py, pg_lease_cases.py and
pg_coordination_cases.py. Tests must execute actual database server-clock and
independent-process schedules. Missing setup, skips, timeouts or zero tests cannot
pass.

#### Upgrade and lease assertions

Assert:

- populated old rows, bytes and receipts;
- rollback and abrupt upgrade loss;
- exact access-control list (ACL) and catalog policy;
- the unmanaged-running preflight and useful v3 recovery before the upgrade.

Lease rules:

- With two workers, exercise acquire replay, renewal, expiry, release, capacity,
  monotonic epochs and original scope.
- A child blocked on admission before expiry must recheck actual server time after
  the lock.
- A stale or missing grant may not claim, reserve or acknowledge inquiry, mutation
  or delivery.
- Public controller commands remain independently authorized and do not grant
  worker authority.

#### Takeover of a paused worker

Pause a real old worker after dispatch reservation or external success, observe
lease expiry and takeover, then resume it.

- The cooperating supplier must deduplicate its stable effect.
- Noncooperation must remain uncertain, with no successor resend.
- Known external truth must stay inspectable while old acknowledgements are
  fenced.
- No database fence alone proves external-call exclusion.

#### Capacity and pressure

Test:

- pending capacity through waits and committed intents;
- retained M1 identities;
- known replay and enrollment at retention capacity;
- late management admission;
- expired inquiry-complete work;
- unsupported legacy intents and signals;
- exhausted epochs.

Require useful eligible work after pressure or expiry. Neither failed display
history nor pruning may erase core receipts or create new identities.

#### Process ownership and demo

Verify:

- one owned process step;
- output, failure and time limits;
- actual SIGTERM drain and forced group cleanup with descendants;
- lease release only after reaping;
- a strict internal claim codec;
- safe real producer metrics and logs.

Rebuild the image and run make phase-f-demo against the actual opt-in worker
profile and the preserved isolated fixture volume. Then retain the original
M1/RTC smoke identity. Keep SQLite inquiry compatibility and the existing Phase E
container proof.

Optional workflow definitions mirror local gates. Hosted CI and publication are
outside the local POC scope. Complete local integration, model and media, and
portfolio release still require their applicable observed evidence.

### Phase G conversation and media lane

Run the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
against the frozen local environment.

- **Offline discovery** includes native AgentSession manual audio→STT→LLM→function
  tools, exact HTTP and grant boundaries, safe report and trace filters, and
  queue, outage and race regressions.
- **The PostgreSQL lane** explicitly requires pg_conversation_cases.py. It
  exercises atomic admission rollback and replay, owner and revision fencing,
  useful progress and projection cursor and history bounds.
- **The installed stack lane** requires real browser-published scripted audio,
  received speech with advancing browser playback, native interruption, end and
  reconnect, and independent durable progress under held dependencies.

Permission denial is a separate negative check. Inspect exported OTLP spans and
numeric SDK reports, plus an independent supplier and receiver record.

- Browser traces, HTTP archive (HAR) files and video must not capture
  credentials. Artifacts contain only allowlisted counts and states and token-free
  UI screenshots.
- Physical microphone and hearing checks and real inference remain separate gates.
- Keep the original M1 identity and prior phase closing artifacts unchanged during
  compatibility runs.
- A failed required lane leaves the phase non-passing.

### Phase H1 declared inquiry baseline

The [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) owns the
completed S-I06/P1-I27 local inquiry measurement and its inspected results. This
is a qualified local baseline, not a full Phase H, P1 or portfolio release. The
frozen [manifest](../harness/workloads/p1-inquiry-v1.json) is authoritative for
this slice. The suggested larger experiments in the load methodology are later
work, not implicit H1 coverage.

#### Commands

From the repository root:

| Task | Command | Notes |
| --- | --- | --- |
| Validate the default declaration and print its canonical digest | `make p1-benchmark-plan` | Returns status not_started without starting a workload |
| Explicitly run the installed API and worker lane | `make p1-benchmark` | Run after its [local prerequisites](../local-setup/README.md) |

Preserve the reviewed manifest and digest before execution. Never change a
schedule, bound or expected result to hide a failed measurement.

#### Frozen experiments

| Frozen experiment | Declared new offers and expectation | Required observation |
| --- | --- | --- |
| steady-w1 and steady-w2 | 20 each, at one-second scheduled spacing; all admitted | Original identities/results and scheduled-versus-actual request timings |
| burst-w1 and burst-w2 | 32 each; four shared HTTP slots; all admitted | Bounded caller queueing plus every applicable persisted inquiry result |
| saturation-w1 and saturation-w2 | 32 each; eight admitted and 24 rejected before workers start | Original-key replay/read at capacity, explicit excess rejection and useful result progress after start |
| Aggregate declaration | 168 offers, 120 admissions, 48 capacity rejections | Expected inputs only; reconcile actual records and independent receipts |

#### Resource and time budgets

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| CPU, memory and pids limits | 1000 millicores, 512 MiB and pids limit 128 | API and each worker | None |
| Experiment time | 180 seconds | Each experiment | Within the 600-second overall budget |
| Cleanup time | 90 seconds | Owned cleanup | A bounded allowance |
| Retention | At most 4096 raw records and the 64 KiB HTTP envelope | Retained evidence | None |

Missing setup, unreadable or missing observations, zero useful progress, a
required timeout, wrong receipts or incomplete owned cleanup cannot pass. The lane
creates source-bound installed containers and UUID-owned schemas and fixtures,
with no checkout mounts. It never resets ordinary M1 data.

#### HTTP observation and timing

- All HTTP operations share one declared semaphore and pool.
- Case observation is one global round-robin GET followed by a 250 ms sleep. HTTP
  and slot delays and cohort sweeps add lag.
- Keep these timestamps separate: the scheduled offer, the first HTTP start, the
  known validated acknowledgement, and the first successful validated submit,
  replay or GET snapshot.
- An unknown attempt finish does not imply acceptance.
- Client-observed result latency includes caller queueing and polling. It cannot
  stand in for a supplier completion timestamp.

#### Resource probes

- Resource probes are sequential in-container Python reads targeting a one-second
  cadence. They record actual start, end, duration and skipped intervals.
- The probes' own CPU, accounted memory and PID overhead is included.
- Verify exact configured caps separately from retained usage overage.
- Cgroup memory is not RSS or a peak. Cumulative CPU microsecond (usec) counters
  have explicit first, last, delta and window values.
- The resource window includes post-inquiry cancellation and delivery checks. It
  excludes host, virtual machine (VM) and shared-database resources.
- Raw samples and count, minimum, median and maximum are sufficient for this small
  baseline. No unsupported tail percentile, media or model result, or production
  capacity is claimed.

See [observability](observability.md) for detailed units and clocks.

#### Evidence and pass conditions

- Retain frozen workload, source, image and machine provenance, bounded safe raw
  records, per-experiment results and failed artifacts under
  .local/validation/p1-phase-h.
- Original failures retain their fixed-enum code and operation, and the observed
  exit, timeout, budget and elapsed metadata, before temporary capture removal.
  Cleanup failures remain separate.
- Reject retention of raw argv, output, environment, body or exception data.
- Automatically collected host platform, architecture and Python, and the
  installed runtime architecture, differ from the separately collected Docker VM
  hardware and shared-host context. Label the supporting environment.json
  accordingly.
- A pre-cleanup measured snapshot is not a phase pass. Require independent inquiry
  reconciliation, unchanged booking with zero mutation, and verified owned
  cleanup.
- Explicit post-inquiry cancellation, final business state and receiver delivery
  stay distinct.
- Preserve closed Phase G artifacts when running the required actual browser
  regression for the Phase H console change.

#### Related Phase H results

The H2 restart, slow-dependency, saturation and shutdown gates and the P1-I26
host/Linux artifact, API and genuine-consumer gates passed separately. P1 V1 is
qualified for the local POC using provider_real v2. local_real remains
unqualified, and complete P2/P3 acceptance remains pending. This H1 lane alone
registers no complete charter runner.

### Current local P1 qualification

P1 V1 retains its selected provider_real v2 local qualification from
[0019](work-items/0019-p1-phase-h-release-qualification.md). The later booking-v5
rerun in [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md)
passed BASE-01 and P1-01 through P1-19; its fresh P1-20 provider result remains
open with the approved certificate bundle prerequisite. The
[build plan](build-plan.md#p1-qualification) keeps the current summary.
Historical reports retain their original source and profile scope.

local_real remains unqualified. Complete P2/P3 acceptance remains pending, and
hosted CI and publication are outside this local POC.

## P2 and P3 lanes and selected checkpoints

This section records the P2 and P3 lanes, then each selected checkpoint in
delivery order. Each linked work item owns its frozen cases and observed results.
No selected pass registers a complete charter row.

### P2 PostgreSQL, dispatch and demo lanes

| Task | Command | Notes |
| --- | --- | --- |
| Run the explicit real PostgreSQL lane | `make p2-postgres-check` | Use a fresh `--report` path under `.local/validation/p2-postgres` when retaining a run |
| Run the task P2-I07 dispatch lane | `make p2-dispatch-check` | None |
| Run the public standalone example | `make p2-demo` | Also selects the new-process receipt and operation-key replay checks |

PostgreSQL lane rules:

- It requires the existing init, start and prepare-postgres setup and the pinned
  host Node.
- It creates only marked UUID schemas and uses separate owner and runtime
  credentials.
- Default Vitest discovery excludes its non-test-named PostgreSQL file, while
  TypeScript still checks that source.
- Missing setup or cleanup never becomes a skip.

The PostgreSQL lane verifies signed challenge possession, protected epochs and
revocation, concurrent durable replay, receipt and intent atomicity, paging and
caps, schema and privilege drift, and actual accepting-process termination after
commit.

Task P2-I07 adds explicit v2 claims, immutable prepared dispatch and
cooperating-acceptor recovery through make p2-dispatch-check. The full lane
includes these five actual cases. Broader restart schedules, the outbox, carrier
delivery and media retain their later gates. The separate gateway and owned
scripted-agent lanes prove their selected restart boundaries; those are not
complete P2 charter rows.

The make p2-demo preview remains pending/not_executed, and operation inspection
is not dispatch.

### P3 contract, HTTP and coordinator lanes

| Task | Command | Notes |
| --- | --- | --- |
| Run the public-export handler and client example | `make p3-demo` | None |
| Run the coordinator lane | `make p3-coordinator-check` | Exercises actual P1 PostgreSQL, postcommit process termination and replay, scope isolation, and separate Python-to-TypeScript client transport |

- P3's contract tests remain provider-free.
- The P3-I05 suite uses actual loopback sockets for authentication, strict
  framing, held work, timeout and disconnect, response validation and cleanup.
- P3-I06 adds immutable coordinator submission through the public P1 work_api.
  The coordinator owns no side ledger.

The coordinator check's case preflight fixture is synthetic, and its transport
probe is not a P1-issued execution. No coordinator invocation, durable result, delivery or
action, or specialist recovering queue is qualified here.

The local PostgreSQL runtime credential is shared with P1 for these fixtures.
That does not prove independent P1/P3 database principals. A separately exposed
deployment requires an isolated principal before qualification.

### Shared static checks

- Root frontend validation includes all four workspace TypeScript packages (the
  console, P2, the P3 specialist and the channel-policy gateway). It also runs
  pinned Prettier checks for P2/P3 source and tests and for selected console and
  gateway files.
- Python checks include the new P3 contract and trust modules and the strict host
  PostgreSQL wrapper.
- Package-level malformed, wrong-scope, resource, expected-error and
  useful-progress tests stay mandatory.

### Revision routing and complete P3 lab acceptance (0031)

The [completed routing and acceptance phase](work-items/0031-revision-routing-and-delegation-acceptance.md)
adds equivalent case CAS qualification for both selectable authorities: the
standalone reference store and P1.

Under each selected authority, P2-I10 must retain:

- a real two-command blocking graph;
- one winning revision despite skewed occurrence timestamps;
- a stale conflict and valid subsequent progress;
- an unchanged request;
- a postcommit lost ACK.

No matching later state may be relabelled as the original command receipt.
Integrated P1 reads and revisions use the public bridge with fixed trusted
bindings, and serving code gains no DDL. Current association revocation is not
atomically rechecked by retained inbox inspection or by this cross-authority CAS.
Complete P2-12 remains a later gate.

P3-01, P3-03 and P3-11 are registered lab cases with fresh passing reports:

| Case | Assertions |
| --- | --- |
| P3-01 | 13 actual completion and action assertions |
| P3-03 | 8 independent-process concurrency and identity assertions |
| P3-11 | 12 complete schema, scope, input, output and image-resource rejection assertions |

Run make p3-contract-check for the P3-03 and P3-11 direct components. The harness
selectors below execute fresh complete cases:

```sh
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

Use the existing restricted-role local PostgreSQL and pinned Node setup.

- Missing setup, wrong inventory, stderr contamination, skipped assertions, stale
  or mismatched report bytes, or incomplete owned cleanup cannot pass.
- The acceptance wrapper retains a fresh component path and hash, and matches
  validated stdout to that file.
- Oversized image rejection happens before decoding. It does not qualify image
  extraction or multimodal inference.

Seventeen P2 and fourteen P3 rows remain planned, so their full project and
ecosystem aggregates remain incomplete.

### Linked confirmation and result projections (0032)

The [completed linked-confirmation and projection phase](work-items/0032-linked-confirmation-and-result-projections.md)
recorded passing separate P2 authority/race and P3 projection lanes. Preserve
those exact source-bound assertions when changing their behavior.

For P2, prove:

- the stale-A/current-B schedule, in which a stale confirmation A clarifies while
  a current confirmation B produces an exact intent receipt;
- actual revision-versus-confirmation lock ordering;
- linked-response, digest and current-association rejection;
- a postcommit lost ACK plus original-command receipt replay;
- one independent fake effect and owned cleanup.

For P1 work v4, require:

- owner adoption with byte preservation, repeat and rollback;
- actual SIGKILL recovery;
- all historical issued references;
- atomic live result and event commit;
- a real blocked completion graph;
- scoped, source and ahead cursor negatives;
- v4 delivery and guarded-action/effect compatibility;
- full old PostgreSQL regression and a fresh installed wheel.

For P3, require:

- atomic derived rows and checkpoint;
- restart and replay;
- immutable as-of observations;
- capacity, unknown and definite-malformed results;
- strict public source checks;
- no execution or delivery side effects.

Failed fixtures and missing required setup remain non-passing. These selected
contributions register no additional complete charter row and do not qualify
native media.

### Outbound replies and completion processing (0033)

The [completed outbound-reply and processing phase](work-items/0033-outbound-replies-and-completion-processing.md)
has these requirements.

P2 requires:

- actual owner inbox-v3 migration, backup and restart;
- immutable enqueue;
- current-route and suppression reservation races;
- known ordinary fake-carrier progress;
- unknown-call ownership.

P3 requires:

- owner projection-v2 preservation;
- separate scan and terminal-watermark assertions;
- progress for a later result B while an earlier result A stays unknown;
- exact receipt binding;
- real precommit and postcommit process loss;
- concurrent ACK CAS;
- complete receiver and SQL reconciliation.

At the 0033 checkpoint, P1 APIs and runtime were unchanged, with all 77 payloads
compared to the existing qualified artifact instead of rerunning unrelated
provider behavior. Preserve that source-bound evidence; later P1 changes require
their own affected gates. Missing setup, skips and timeouts remain non-passing.

Recorded results:

| Check | Result |
| --- | --- |
| Selected gates | The 24-case P2 and 16-case P3 lanes and isolated installed consumers passed |
| Fresh P2 regressions | Recovery, routing and confirmation passed (23, 22 and 18 assertions) |
| Fresh P3 regressions | Projection, coordinator and execution passed (12, 10 and 12 assertions) |
| Fresh registered case regressions | P3-01, P3-03 and P3-11 passed (13, 8 and 12 assertions) |
| Shared checks | The phase recorded 1,501 Python and 723 TypeScript tests, broad typing over 133 and strict typing over 95 sources, and 321 formatted Python files |

No new complete charter row follows from these selected contributions.

### Callback evidence and applicability refresh (0034)

The [completed callback and applicability phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
completed the selected local phase gates for P2-I13 and P3-I11. Freeze exact child
inventories and finite work and cleanup budgets before actual runs.

P2 callback gates require:

- separate HMAC, signature-window and scope negatives;
- semantic replay and conflicts;
- exact original-attempt correlation before send acknowledgement and after
  reassignment;
- deterministic reordered and conflicting evidence;
- both admission-veto orders, with useful unrelated progress;
- restore of populated v4 callback records and receipts, with unchanged old inbox
  and outbox bytes.

The P3 gate freezes 18 cases and 20 owner/runtime modes, five PID-owned kills and
one actual CAS blocking graph. It requires:

- populated eight-table versioned-profile-row restore;
- exact old and new source, ACK, receipt, refresh and tombstone joins before,
  after and on reopen;
- late result A versus a valid, independently confirmed B;
- stale and unavailable observation handling;
- progress for unresolved results hidden from display.

This is not pg_dump or stale-branch recovery proof. Strict JSON primitive types,
first-failure precedence and complete owned cleanup are required. Fresh offline
installed consumers and old regression lanes must pass before selected task
completion. Missing, skipped or timed-out gates remain non-passing. Full P2/P3
registrations and media remain separate.

### Send policy and action races (0035)

The [completed send-policy and action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local qualification for P2-I14 and P3-I12.

#### P2 send-policy requirements

- P2 must continue to preserve populated v4 rows during owner v5 adoption and an
  actual populated pg_dump/psql restore and reopen.
- Keep ordinary provider-observed response loss unknown.
- Separate known, absent and unavailable lookup from permission for a new explicit
  cooperating retry.
- Match stable operation bytes and key, distinct local attempts, callback
  exact-attempt correlation, current permission and both veto orders.
- Concurrent controller commands, replay, conflicts and caps, process loss and
  actual late I/O ownership must preserve useful progress and independent ledger
  truth.

#### P3 action-race requirements

P3 requires two actual SQL blocker chains with two simultaneous writer waiters.
They use the same prewarmed owner observer and the unchanged 1000 ms lock timeout.

- Revision first: A is rejected atomically, and an independently confirmed B is
  allowed.
- Intent first: the B revision fails, while A's original receipt and effect
  survive.
- Assert all pre-intent, claim, reservation and known-effect cancellation
  boundaries.
- Perform three owned kills: action before commit, action after commit, and
  supplier success before local finish. Fresh processes reconcile original
  identities without reapplication.

The closed 31-mode, 16-case protocol reserves 15 of 180 seconds for cleanup,
permits at most 32 child calls, and bounds capture and report bytes. Strict
primitive and PID-marker negatives, exact full joins, public installed consumers
and fresh old regression lanes are required. Diagnostic mode can never qualify.
P1/P3 runtime bytes remain unchanged, and broader deadline, recovery and media
rows stay pending.

#### Recorded checkpoint results

| Check | Result |
| --- | --- |
| Python tests | 1,660 passed (49 P1, 14 P2, 238 P3, 1,359 root) |
| TypeScript tests | 861 passed (326 console, 457 P2, 78 specialists) |
| Typing and formatting | Broad typing over 138 and strict typing over 108 sources; 340 files passing Ruff formatting |
| Selected gates | The 30-case P2 and 16-case P3 source gates, isolated installed consumers and prior 111 P2/101 P3 regression assertions passed |

These are correctness checks, not production capacity or real-media measurements.

### Native input and deadline cancellation (0036)

The [completed handoff](work-items/0036-native-input-and-deadline-cancellation.md)
records these independent boundaries. Selected P2-I15/I16 and P3-I13
implementation, artifact, compatibility and final shared gates passed, including
the affected media rerun. These selected tasks are complete; full charter release
remains separate.

| Boundary | Evidence at the completed native/deadline checkpoint | Qualification limit |
| --- | --- | --- |
| P2 native code | Fifty-five Python, 530 P2 TypeScript, sixty-five browser-policy and forty-five wrapper tests passed; one separate actual local HTTP proxy-routing regression passed | Final shared checks passed separately; these focused counts do not establish full charter release |
| P2 native actual gate | Final current six-group run passed in 31.063 seconds with 24 children, one owned kill and one SQL graph; actual browser text/WAV committed voice, two SDK replies, returned text/audio, v6 restore and complete cleanup | Affected UI-hint media rerun passed; SDK/storage assertions are separate from the six browser groups, and microphone/general inference quality remains unqualified |
| P2 installed Python | Selected isolated default/optional-native wheel, sdist and rebuilt wheel retain six runtime payloads; eight exact source copies passed fifty-five local SDK/HTTP tests | No RTC, PostgreSQL, real provider or physical microphone claim; preserve the earlier fifty-one-test package as historical |
| P2 installed npm | Seventy-eight current dist/README payloads plus semantic manifest; actual public v6 PG/HTTP receipt-before-prepare and fresh-process original replay passed with prepare/operation calls one then zero | Synthetic read-only case and operation ports; no P1 booking, RTC/media or supplier/provider qualification |
| P3-I13 | Eighteen source and eighteen isolated installed assertions passed; existing execution/applicability/action races contribute forty-six compatibility assertions | Preserve exact reports, failures, direct safe proof files and unchanged runtime payloads; no full recovery/release claim |
| Compatibility | P2 old lanes passed 141 assertions plus one focused regression; P3 execution/applicability/action lanes passed forty-six assertions | Preserve exact selected reports; broader P3 recovery and complete product rows remain planned |
| Shared fast/frontend | 1,788 Python checks (P1 49, P2 55, P3 251, root 1,433), zero skips/violations, Ruff, broad/strict typing over 141/116 files and Python formatting over 355 files passed; 1,000 TypeScript tests (console 392, P2 530, P3 78), types, formatting and builds passed | This is the historical native/deadline checkpoint, not the current phase or a rerun of full P1 database/provider qualification |
| Shared/default stack | Eight ordinary stack checks and ten audio frames passed with original M1 preserved; native schema/room residuals were zero after cleanup | Inference disabled transport checks; existing provider/P1 qualification remains historical unless rerun |

#### Native storage and intake rules

- The P2 owner-only v6 upgrade adds two native tables under quiescence, without
  serving DDL or deleting prior inbox, outbox, callback or recovery identity.
- New intake, prepare and reservation use fresh database time after the admission
  and binding locks. Retained facts and an already admitted possible call are
  distinct.
- Genuine final recognition preserves the original turn before awaits.
  SDK-promoted interim text cannot enter durable intake.
- Default SDK text and SessionHost consumption are disabled, and StopResponse
  prevents automatic generation.
- Acceptance must precede explicit dispatcher-owned SDK generation, with one input
  and operation identity.

#### Resource ownership and evidence limits

- Retain actual socket, reader, turn, intake, prepare and observer work until
  settlement.
- Close failures cannot skip independent owners or manufacture zeros.
- Inspect the original eighteen native producer metrics, bounded safe logs, telemetry
  outages and six-key generation observations separately from browser playback.
- No paid provider call, physical microphone, general automatic speech
  recognition (ASR) or model quality, or complete P2/P3 row follows from scripted
  code tests.

Catalog registrations remain 24 of 55.

### Case rehydration and standalone qualification (0038)

The [completed handoff](work-items/0038-case-rehydration-and-standalone-release.md)
separates focused units, actual durable and media gates, and installed consumers.

| Gate | Recorded result |
| --- | --- |
| P2 storage | Eighteen assertions passed in 6.534 seconds |
| P2 media | Three actual media groups in one Playwright case passed in 35.797 seconds |
| P2 Python package | The nine-payload package passed 111 tests in fifteen commands and 52.364 seconds |
| P2 npm consumer | The isolated consumer passed seven stages in 2.1696 seconds |
| P3 package | Eight offline plus eight actual installed assertions passed in 58.885 seconds |
| P2 compatibility | All 166 selected assertions passed in 98.997 seconds |

No selected pass registers a full charter row.

Final shared gates passed:

| Check | Result |
| --- | --- |
| Tests | 2,148 Python tests and 1,224 TypeScript tests (503 console, 632 P2, 89 specialist) |
| Typing and formatting | Broad and strict typing over 144 and 132 files, and Python formatting over 387 files |
| Documentation | Validation for 113 documents, with all 29 Mermaid bodies passing syntax-only parsing |
| Stack | Ordinary doctor and smoke with ten audio frames and original M1 state preserved |

The catalog remains 55 defined and 24 registered. All 17 P2 rows and the remaining
14 P3 rows stay planned.

#### Commands and pass conditions

The two P2 commands use the existing local restricted-role PostgreSQL, SFU and
browser prerequisites.

| Task | Command | Notes |
| --- | --- | --- |
| Run the P2 rehydration check | `make p2-rehydration-check` | None |
| Run the P2 rehydration media check | `make p2-rehydration-media-check` | None |
| Check the P3 offline artifacts | `make p3-package-check` | None |
| Run the explicit combined P3 package validation | `make p3-package-lab-check` | None |

Preserve failed attempts, exact named assertions, owned process and SQL ordering,
complete original receipt joins and populated restore. Manifest validation binds
every physical retained file, including nested summaries, and excludes only its
own descriptor file. Guard shared readers and DDL until actual owners settle.
Missing setup, a timeout, skipped work, unresolved cleanup or absent proof cannot
pass.

### Workload and image gates (0039)

The [completed handoff](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records completed selected P2-I19/P3-I16 qualification. Freeze sources, roles,
schedules, private proofs and numeric study ceilings before a normal run, and
preserve original failures. These lanes add no catalog registration or full
release claim.

| Lane | Selected inventory and bound | Required interpretation |
| --- | --- | --- |
| P2 workload | Twenty-four named assertions; seed 39; 360 seconds including 20 cleanup, at most 32 children, 8 KiB per stream/512 KiB aggregate capture, 2 MiB direct proof and 32 KiB report | Actual restricted-role PostgreSQL/HTTP admission, retained identities, second-scope progress, dormant inspection, fresh-process reopen, populated restore and complete cleanup; selected local qualification passed |
| P2 study ceilings | Admission 5 seconds, useful completion 15 seconds, sampled event-loop maximum 1 second and sampled Node RSS 512 MiB | Fixed selected local failure ceilings; report clock/sample scope and actual observations, not throughput, tenant fairness or production capacity |
| P3 image source | Twenty named assertions: eight cross-language/structural/factual and twelve actual socket/lifecycle; 120 seconds including 20 cleanup | Actual PNG guards, zero provider entries for invalid/expired work, eight scripted provider admissions, independent literal facts and actual resource settlement; selected local qualification passed |
| P3 image installed | Fresh maintained offline-eight artifact builder followed by the same twenty image assertions; 360 seconds including 20 cleanup, at most 32 shared children, 64 KiB streams/2 MiB aggregate capture, 32 KiB proofs/report | Public isolated Python/npm consumers, unadapted declared fixture/helper inputs, exact physical retained index and source/archive scope; not twenty PostgreSQL scenarios or vision inference |

#### Supported PNG subset

P3's supported PNG subset is noninterlaced RGB8 or RGBA8, at most 2 MiB encoded
and 2048×2048 pixels, with bounded chunk, CRC, zlib, scanline and filter
validation.

- Require actual worker exit 0, a fresh original-deadline check before provider
  work, and retained provider promises after timeout or cancel.
- Structural validation does not prove extracted values or regions. Independent
  valid-JSON negatives with wrong values or swapped regions must fail factual
  evaluation.
- P1 remains policy-only. No durable image execution or action follows.

Selected P2-I20/P3-I17 qualification is recorded in the next section.

### Operations and fixed-policy gates (0040)

The [operations and policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md)
owns the frozen cases and actual results for P2-I20/P3-I17. Selected normal
qualification passed; complete charter rows retain their own gates.

| Lane | Required inventory | Predeclared bounds and evidence |
| --- | --- | --- |
| P2 operations | Sixteen actual PostgreSQL/HTTP groups and three browser groups in one actual Playwright case | 240 seconds including 20 cleanup; thirteen normal children, ceiling 24; 8 KiB/stream, 512 KiB captures, 1 MiB/direct proof, 16 MiB retention and 32 KiB report. Independent complete durable snapshots and original identity/provider/callback joins; actual zero owned occupancy after closure |
| P2 UI/lifetime | Read-only transitions, paging, failure/recovery, exporter outage and Forget while a real case read is held | Token-free screenshots and allowlisted finite browser observations; raw browser streams/reports are not retained. Backend late-work ownership and unit positive late-result epoch fencing are separate proofs |
| P3 fixed policy source | Eight contract/factual/cross-language and twelve actual HTTP/lifecycle assertions | 120 seconds including 20 cleanup; six direct commands. Fresh fourteen-module private compile and staged unadapted public consumers; no ambient dist authority |
| P3 fixed policy installed | The same twenty assertions from fresh isolated public artifacts, plus eight separately counted offline package assertions | 360 seconds including 20 cleanup; twenty-seven normal direct/nested commands, ceiling 32; 64 KiB/stream, 2 MiB captures and 32 KiB/direct proof/report |

#### P2 operations requirements

- P2 final disclosure after a held external case read uses fresh PostgreSQL time
  and current permission.
- This new gate has zero SQL waiter graphs. Unchanged lock-time freshness is
  verified separately by the required fresh P2-I18 eighteen-group storage
  regression.
- Preserve the existing actual media compatibility lane.
- The new UI studies revision 0 as read-only and introduces no storage version or
  mutation.

#### P3 fixed-policy requirements

P3 requires:

- all applicable rule and fact witnesses;
- exact source, version and digest binding;
- structural acceptance separated from factual truth;
- original request fingerprints;
- seventeen receiving-path negative probes;
- actual held-work settlement.

Evidence rules:

- The parent independently joins client canonical wires with server request and
  result observations. They are not raw TCP captures.
- Source and installed reports are separate from the nested offline-eight artifact
  report.
- Preserve v1 defaults, image HTTP and current durable-policy compatibility.
- Missing setup, skipped cases, timeouts, unverified sources, secret captures or
  incomplete cleanup cannot pass.

#### Recorded 0040 results

- **P2:** sixteen PostgreSQL/HTTP groups plus three actual browser groups, the
  isolated npm consumer with 105 payloads in seven stages, and 187 current
  compatibility assertions.
- **P3:** twenty source and twenty installed fixed-policy assertions, separate
  offline package checks, both twenty-assertion image compatibility gates, and 146
  existing compatibility assertions.

The maintained sixteen-assertion P3 package composition is included in the 146,
not an extra sixteen PostgreSQL-only scenarios.

#### Snapshot retention and evidence sealing

- Eight complete P2 owner snapshots use separate canonical files of at most 1 MiB
  each and a manifest of at most 32 KiB with path, type, hash, byte-count and
  table-count entries.
- Aggregate retention stays at 16 MiB. All rows and catalog data and independent
  before/after joins remain present.
- Current packaged README prose changes have exact source/archive equivalence
  reviews and fresh offline artifact checks. Original actual installed archives
  keep their original README bindings.
- Two added foundation entries only discover the new P2 producer/lifetime
  regression file. They change no runner registrations.
- Final source census, ancestor and link safety, immutable prior checkpoints,
  exact physical retained sets and owned cleanup are verified before sealing
  evidence.

### Standalone application and durable-v2 prerequisite (0041)

The [completed 0041 work item](work-items/0041-standalone-channel-and-durable-policy.md)
owns the premeasurement manifests, source bindings, closed role and process
inventories, and observed results for P2-I21 and the P3-I18 durable prerequisite.
These are selected implementation gates, not new acceptance registrations.

| Gate | Recorded result |
| --- | --- |
| P2 | 20 installed standalone, a separate 6 public-P1 and 187 compatibility assertions passed |
| P3 | 12 source, 12 installed, a separate 8 offline and 146 selected compatibility assertions passed |
| Shared checks | 2,537 Python and 1,501 TypeScript tests; broad and strict typing over 150 and 156 files; Python formatting over 433 files; documentation validation for 119 documents |

Historical compatibility is bound to original source bytes. The reviewed
exception-code annotation preserves runtime behavior, while fresh source and
installed gates bind the final bytes and the installed public type regression.

#### P2 installed starter

P2's installed starter must demonstrate routing, original history, synthetic
delivery and restart without P1/P3 services.

- Its single owned process kill follows an actual flushed HTTP acknowledgement.
- External commit or ACK loss is a separate bounded transport fault with a fresh
  lookup.
- A distinct installed public-P1 contract repeat cannot be counted as standalone
  behavior or inferred from earlier reports.

#### P3 durable-v2 prerequisite

P3's twelve measured assertions exercise explicit v2 acceptance and issued
execution, strict immutable evidence, original replay, expired and cancelled
historical facts, abandoned-owner retention, and fresh lookup after one owned
postcommit kill.

- Source and isolated installed runs remain separate. Installed mode also executes
  the eight separately counted offline artifact assertions.
- Verify the exact Python 36-payload and npm 32-payload inventories rather than
  accepting a larger arbitrary package.
- The maintained current v1 policy and image gates and the full compatibility
  gates remain required when their shared client or core changes.
- SDK, native, browser and media behavior and real inference are separate
  following gates. No scripted durable fixture qualifies them.

### Native fixed-policy RTC text (0042)

The [0042 handoff](work-items/0042-responsive-native-policy-and-compact-demo.md)
records selected P3-I18B qualification over one configured native session and
the explicit durable policy-v2 facades.

| Lane | Command | Retained scope |
| --- | --- | --- |
| Inert plan | `make p3-native-policy-plan` | Declares the selected inventory; starts no work |
| Source journey | `make p3-native-policy-check` | Twelve backend/SDK assertions and three browser groups passed |
| Installed journey | `make p3-native-policy-package-check` | The same selected assertions passed from isolated artifacts; eight offline package assertions remain separate |

The gate distinguishes acknowledged P1 work, the retained background runner,
useful RTC-text progress while the specialist is held, and the compact as-of
result view. SDK waiter termination does not business-cancel P1 work. This profile
does not qualify microphone capture, speech recognition, audio playback, provider
quality or complete joined voice/SMS routing.

### Stable result delivery and package separation (0043)

The [0043 work item](work-items/0043-stable-result-delivery-and-return-context.md)
owns the selected source gate. A separate result-receiver package gate covers the
built archives.

| Lane | Inventory and bounds |
| --- | --- |
| Selected source gate | Sixteen actual storage assertions and four actual return assertions; 180 seconds including twenty cleanup seconds; sixteen owned groups |
| Result-receiver package gate | 360-second total bound including twenty cleanup seconds; at most 32 groups; a fixed 25-group successful schedule |

#### Source gate scope

P2 v8 old-surface coverage is selected outbox inspection, native bind and revoke,
and current-case inspection. The eleven historical compatibility lanes keep their
original profiles. They do not establish every API on v8.

#### Package gate scope

The package gate builds fresh Python and npm archives, verifies source, archive
and install payloads, and uses isolated consumers.

- Its eight original offline assertions and twenty copied fake-port tests claim
  zero actual storage or return assertions.
- Require indexed final process-group states and the exact private physical
  inventory.
- Missing indexes, unsafe modes, incomplete closure and elapsed deadlines remain
  non-passing, even when individual consumers succeed.

Joined RTC/voice/SMS and provider/video gates remain separate from both lanes.

### Original channel-input binding (0044)

The [0044 handoff](work-items/0044-origin-bound-channel-policy.md) records selected
original-input qualification toward P2-I22 and P3-I19.

| Lane | Command | Retained scope |
| --- | --- | --- |
| Inert plan | `make channel-origin-plan` | Declares the bounded source schedule |
| Unit contracts | `make channel-origin-unit` | Cross-language origin and typed policy facade checks |
| Actual source gate | `make channel-origin-check` | Fourteen assertions across sixteen owned process groups passed |
| Isolated package gate | `make channel-origin-package-check` | Built and installed public artifacts with explicit fake ports; not an actual database repetition |

The source gate joins original native or signed simulated-SMS input to P1 work,
issued policy results and the current P2 receipt/read. It uses three disposable
schemas and one owned acknowledgement-host kill after commit. Complete original
identity joins and owned cleanup remain required. These source and package
results do not establish the later joined RTC/provider journey, whole-stack
restart or complete charter release.
