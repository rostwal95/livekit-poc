# P3 controlled native baseline and remote-isolation decision

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the controlled P3 native baseline and the decision to test a remote read-only boundary |
| Audience | Engineers changing P3 native orchestration or the remote specialist boundary; reviewers; coding agents |
| Scope | Tasks P3-I01 and P3-I02 and the initial P3-16 baseline; excludes durable delegation, media and package qualification |
| Owns | P3-I01 and P3-I02 change plan, remote-boundary decision, observed verification and handoff |
| Related | [P3 charter](../projects/delegation-reliability-scope.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [P2 channel contracts](0022-p2-channel-contracts.md) · [Specialist contracts](0025-p3-specialist-contracts-and-trust.md) |

## Behavior and scope

This work item implements tasks P3-I01 and P3-I02 before work package PLAN-17 of
the [build plan](../build-plan.md). It uses the frozen Python 3.14 / LiveKit
Agents 1.8.11 environment. It compares two modes over the same immutable synthetic
policy input and fixed rule:

- a native single-agent async tool;
- a real native AgentTask inside TaskGroup.

This contributes only to the initial controlled baseline of acceptance ID P3-16.
All 17 product acceptance rows remain planned and unregistered.

| Criterion | Given | When | Safety | Useful progress and evidence |
| --- | --- | --- | --- | --- |
| Equivalent controlled result | Same accepted immutable PolicyInput and synthetic-notice-v1 | Run both modes with the fixed model/tool fixture | Equal input fingerprint, revision, rule and outcome; no mutation authority | Actual software development kit (SDK) tool dispatch and eventual SDK-observed result in both modes |
| Held responsiveness | One evaluation held on an asyncio.Event barrier | Ask what read-only means before releasing the barrier | Zero completed result while held; no fabricated success | Real SDK assistant explains read-only permission while evaluation remains active |
| Bounded input | Exact supported fields and fixed schema/policy | Send malformed, duplicate, unknown, wrong-type, excessive or invalid Unicode input | Safe invalid_input before session construction; no reflected values | A valid bounded input completes with eligible or clarification outcome |
| Cancellation and timeout | Owned native session/task/model and one held evaluation | Cancel caller or hold the fixture-model response past budget | Cancellation propagates; no remaining evaluation/task; fixed safe timeout | Fresh normal runs still pass; cleanup failure cannot be certified as complete |
| Safe diagnostics | Secret-shaped note or synthetic external error | Inspect report, library events and CLI failure output | No note, provider exception, chained traceback or credentials in output | Finite result/error codes remain inspectable |

Bounds were declared before the retained baseline run:

| Limit | Value |
| --- | --- |
| Active evaluations | One per run |
| Input JSON | 2048 bytes |
| Encoded note | 512 bytes |
| Fixture-model calls | At most 24 |
| Experiment | 15 seconds |
| Cleanup | A shared 3-second budget |

Comparisons contain one ordered sample per mode, without warmup. First use can
include SDK cold initialization. No percentile, latency-superiority or capacity
claim follows.

## Interfaces and ownership

### Package layout

| Component | Path | Responsibility |
| --- | --- | --- |
| Development workspace distribution | `projects/delegation-reliability/python` | Development-only member; not introduced into P1 serving dependencies |
| Source | `src/delegation_reliability`, inside the distribution | Package source; no import starts a server, reads provider credentials or downloads a model |
| Project tests | `projects/delegation-reliability/tests` | Focused unittest suite |
| Root tooling | Repository root | Member and dependency registration, frozen resolution and actual root discovery |

### Policy values and runtime state

`PolicyInput` is an immutable bounded value with a canonical fingerprint.
`PolicyResult` contains the revision, fingerprint, supplied policy version, rule
and an eligible or clarification outcome. This baseline accepts synthetic facts,
not authenticated customer facts. The result grants no action authority.

The model dispatches exact allowlisted fixture commands. It does not perform
general reasoning or fabricate model token usage. Runtime state belongs to the
local experiment and the native SDK. There is no accepted durable work, database
schema, tenant authorization or retry scheduler in this slice.

### Native modes

The native mode uses the real public `AgentTask`, `RunContext` and `AgentSession`
APIs and the selected SDK's `beta.workflows.TaskGroup`/`TaskGroupResult`.
TaskGroup temporarily controls the same session and copies its conversational
context; it is a foreground supervisor construct. Task-level tool progress
releases its conversational turn.

The standalone tool has no task/group handoff and receives the same captured
immutable input. Group summarization is disabled to avoid adding an unrelated
model call, but fixed model prompts and control transitions still differ. Neither
mode uses a separate reasoning-model context or establishes background-model
quality.

### Remote-boundary decision

Retain native tools for ordinary local orchestration, and AgentTask/TaskGroup for
bounded supervised conversation steps. They suffice for the controlled fixture.

Proceed to the planned remote read-only TypeScript capability. A separate process
can isolate language and dependencies, permissions and resource budgets, and can
be killed independently for recovery tests. These benefits are design reasons to
test, not capabilities established by Phase P3-A. Native tasks share the Python
process and do not independently survive its loss.

The remote boundary adds serialization, authentication, cancellation ambiguity,
network latency and operational cost. It is not selected for assumed speed:

- P1 remains the sole durable execution owner. P3 supplies bounded attempt
  observation, source/result applicability and a handler adapter. Do not add a
  service-owned queue.
- Before real persisted P3 invocation, finish its scoped request/result contract,
  principal/resource boundary and public P1 adapter gate.
- PLAN-21 still requires a controlled three-way comparison, including the actual
  background-subagent pattern and equivalent selected real models where
  applicable.

The upstream [workflow guide](https://docs.livekit.io/agents/logic/workflows/)
distinguishes supervised tasks from the
[background delegation pattern](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/).
The exact pinned SDK APIs were inspected and exercised. This is not a dependency
upgrade or a claim that the beta TaskGroup import remains stable in future
releases.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). Phases P3-C, P3-E and task P3-I15 are
defined in the
[P3 task plan](../implementation/p3-delegation-reliability.md).

| Gate | Exact lane / criterion | Evidence and completion rule |
| --- | --- | --- |
| G-READY/CONTRACT | Immutable policy facts, canonical fingerprint, exact types/fields/limits, known useful fixture and explicit native context differences | Reject invalid input before SDK session creation; preserve current positive outcome |
| G-FAST | Focused unittest suite, Ruff format/lint and strict mypy on all new source; root full fast/format checks | No zero-test discovery, missing suite or required skip passes |
| G-OBS | Inspect real named library events/report and sentinel SDK errors at API/CLI boundaries | INFO start/closed/completed; fixed ERROR failure/cleanup codes; no raw note/error text; no fabricated exporter |
| G-DURABLE | Not claimed: no database, durable delegation or worker process in this baseline | P3-C owns actual independent-process recovery |
| G-MEDIA | Not claimed: native in-process text orchestration only | P3-E owns browser voice/interruption/routing |
| G-PACKAGE | Root installs/discovers the workspace member; no isolated artifact qualification claim | P3-I15 owns later wheel/npm consumer evidence |

Executed focused commands from the repository root:

```sh
.venv/bin/ruff check projects/delegation-reliability/python/src projects/delegation-reliability/tests
.venv/bin/ruff format --check projects/delegation-reliability/python/src projects/delegation-reliability/tests
.venv/bin/mypy --strict projects/delegation-reliability/python/src
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v
.venv/bin/python -m delegation_reliability
```

Test design:

- Success and cancellation lanes use the actual SDK without replacing native
  lifecycle methods.
- A held fixture-model stream tests timeout. Synthetic failing SDK/close
  boundaries test safe containment.
- Tests inspect owned task sets after cleanup, including caller cancellation
  during native task control.
- Unexpected cleanup errors and close timeouts remain non-passing. A primary
  cancellation retains its identity and receives a fixed cleanup-failure note
  rather than a false success.
- Each failure test explicitly identifies its fake or synthetic boundary.

## Results and handoff

### Focused results

| Check | Observed result |
| --- | --- |
| Final focused suite | Passed 18 tests with zero skips |
| Lint, formatting, strict typing and independent review corrections | Passed |
| Installed example | Passed both actual SDK modes with equal input/result, a meaningful held question, one completed evaluation each, real result observation and complete owned cleanup |
| Native task and group completion | Observed; no Docker or provider calls occurred |
| Final shared validation and independent automated review | Passed; root retained the actual reports and source snapshots |

No final product requirement or remote capability is certified by the focused
task result.

### Shared validation and completion

The [P2 channel contract work item](0022-p2-channel-contracts.md) records the same
shared validation. The first P2/P3 slices passed the final root gates with
independent automated review:

| Check | Observed result |
| --- | --- |
| `make check` | Executed 1,132 Python tests (1,079 root, 21 P1, 14 P2 and 18 P3), with zero skips and zero structural violations |
| Ruff and typing | Ruff passed; maintained typing covered 95 sources and strict typing 35 |
| `make format-check` | Passed for 231 Python files |
| `make frontend-check` | Passed console typing, build and 326 tests, plus P2 source/test typing, build and 64 tests |
| Documentation and diagrams | All 95 documents passed and six project Mermaid diagrams parsed; the invalid syntax fixture was rejected |

Root commands were also tested with temporary failing P2 test and type files. Both
failed as required, and both files were removed before final validation. The
expanded Python discovery negative fixture covers P2 and P3 failure propagation.
Offline frozen installs included both development-only members, without external
version upgrades.

Both Dockerfiles rebuilt. Eight default transport, authentication and M1
(confirmed-investigation intake) checks passed with the original M1 identity and
ten audio frames. An owned nonroot, network-disabled serving-image probe imported
P1 and confirmed that the P2 and P3 development packages were absent. This smoke
does not qualify either new product.

Evidence is retained under
`.local/validation/p2-p3-foundation/8c0eedd87dc746f5b56d02c3c01becc0`. The complete
project acceptance catalogs still contain 17 planned, unregistered rows each. No
paid inference, new business database migration or remote continuous integration
(CI) ran. Previous P1 release artifacts remain intact; these new checks are
separate.

### Assistance and next task

AI assistance implemented and reviewed the bounded experiment and tests. User
review and independent human API feedback are not manufactured.

This completes the controlled P3-A baseline/decision (P3-I01/I02). Actual
background-reasoning quality, remote execution and the P3-16 comparison remain
later requirements. The next bounded task is P3-I03's cross-language contract,
followed by trusted scope/limits before any HTTP handler. Proceed to P3-I03 only
after preserving this scoped baseline. Keep the P1 V1 (fixed version-1 scope)
qualification and its historical source-bound artifacts intact.
