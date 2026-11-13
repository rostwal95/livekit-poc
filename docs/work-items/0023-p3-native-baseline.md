# P3 controlled native baseline and remote-isolation decision

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Implement P3-I01/I02 before PLAN-17 using the frozen Python 3.14 / LiveKit Agents
1.8.11 environment. Compare a native single-agent async tool with a real native
AgentTask inside TaskGroup, over the same immutable synthetic policy input and
fixed rule. This contributes only to P3-16's initial controlled baseline. All 17
product acceptance rows remain planned and unregistered.

| Criterion | Given | When | Safety | Useful progress and evidence |
| --- | --- | --- | --- | --- |
| Equivalent controlled result | Same accepted immutable PolicyInput and synthetic-notice-v1 | Run both modes with the fixed model/tool fixture | Equal input fingerprint, revision, rule and outcome; no mutation authority | Actual SDK tool dispatch and eventual SDK-observed result in both modes |
| Held responsiveness | One evaluation held on an asyncio.Event barrier | Ask what read-only means before releasing the barrier | Zero completed result while held; no fabricated success | Real SDK assistant explains read-only permission while evaluation remains active |
| Bounded input | Exact supported fields and fixed schema/policy | Send malformed, duplicate, unknown, wrong-type, excessive or invalid Unicode input | Safe invalid_input before session construction; no reflected values | A valid bounded input completes with eligible or clarification outcome |
| Cancellation and timeout | Owned native session/task/model and one held evaluation | Cancel caller or hold the fixture-model response past budget | Cancellation propagates; no remaining evaluation/task; fixed safe timeout | Fresh normal runs still pass; cleanup failure cannot be certified as complete |
| Safe diagnostics | Secret-shaped note or synthetic external error | Inspect report, library events and CLI failure output | No note, provider exception, chained traceback or credentials in output | Finite result/error codes remain inspectable |

Bounds are declared before the retained baseline run: one active evaluation per
run, 2048 input JSON bytes, 512 encoded note bytes, at most 24 fixture-model calls,
15 seconds for the experiment and a shared 3-second cleanup budget. Comparisons
contain one ordered sample per mode, without warmup. First use can include SDK
cold initialization; no percentile, latency superiority or capacity claim follows.

## Interfaces and ownership

The development workspace distribution lives under
projects/delegation-reliability/python with source in src/delegation_reliability;
project tests live under projects/delegation-reliability/tests. Root tooling owns
member/dependency registration, frozen resolution and actual root discovery. The
member is development-only and is not introduced into P1 serving dependencies.
No import starts a server, reads provider credentials or downloads a model.

PolicyInput is an immutable bounded value with canonical fingerprint; PolicyResult
contains revision, fingerprint, supplied policy version, rule and eligible or
clarification outcome. This baseline accepts synthetic facts, not authenticated
customer facts. The result grants no action authority. The model dispatches exact
allowlisted fixture commands; it does not perform general reasoning or fabricate
model token usage. Runtime state belongs to the local experiment and native SDK.
There is no accepted durable work, database schema, tenant authorization or retry
scheduler in this slice.

The native mode uses real public AgentTask, RunContext and AgentSession APIs and
the selected SDK's beta.workflows.TaskGroup/TaskGroupResult. TaskGroup temporarily
controls the same session and copies its conversational context; it is a foreground
supervisor construct. Task-level tool progress releases its conversational turn.
The standalone tool has no task/group handoff and receives the same captured
immutable input. Group summarization is disabled to avoid adding an unrelated
model call; fixed model prompts/control transitions still differ. Neither mode
uses a separate reasoning-model context or establishes background-model quality.

### Remote-boundary decision

Retain native tools for ordinary local orchestration and AgentTask/TaskGroup for
bounded supervised conversation steps. They suffice for the controlled fixture.
Proceed to the planned remote read-only TypeScript capability because a separate
process can isolate language/dependencies, permissions and resource budgets and
can be killed independently for recovery tests. These benefits are design reasons
to test, not capabilities established by P3-A. Native tasks share the Python process
and do not independently survive its loss.

The remote boundary adds serialization, authentication, cancellation ambiguity,
network latency and operational cost. It is not selected for assumed speed. P1
remains the sole durable execution owner; P3 supplies bounded attempt observation,
source/result applicability and a handler adapter. Do not add a service-owned queue.
Before real persisted P3 invocation, finish its scoped request/result contract,
principal/resource boundary and public P1 adapter gate. PLAN-21 still requires a
controlled three-way comparison including the actual background-subagent pattern
and equivalent selected real models where applicable.

The upstream [workflow guide](https://docs.livekit.io/agents/logic/workflows/)
distinguishes supervised tasks from the
[background delegation pattern](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/).
The exact pinned SDK APIs were inspected and exercised. This is not a dependency
upgrade or a claim that the beta TaskGroup import remains stable in future releases.

## Failure cases and validation

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

Success/cancellation lanes use the actual SDK without replacing native lifecycle
methods. A held fixture-model stream tests timeout; synthetic failing SDK/close
boundaries test safe containment. Tests inspect owned task sets after cleanup,
including caller cancellation during native task control. Unexpected cleanup
errors and close timeouts remain non-passing; a primary cancellation retains its
identity and receives a fixed cleanup-failure note rather than a false success.
The fake/synthetic boundary in each failure test is explicitly identified.

## Results and handoff

The final focused suite passed 18 tests with zero skips; lint, formatting, strict
typing and independent review corrections passed. The installed example passed both actual
SDK modes with equal input/result, a meaningful held question, one completed
evaluation each, real result observation and complete owned cleanup. Native task
and group completion were observed; no Docker or provider calls occurred.
The final shared validation and independent automated review passed; root retained
the actual reports and source snapshots. No final product requirement or remote
capability is certified by the focused task result.

AI assistance implemented/reviewed the bounded experiment and tests; user review
and independent human API feedback are not manufactured. The next bounded task is
P3-I03's cross-language contract, followed by trusted scope/limits before any HTTP
handler. Keep P1 V1 qualification and its historical source-bound artifacts intact.

### Shared validation and completion

The first P2/P3 slices passed the final root gates with independent automated
review. make check executed 1,132 Python tests: 1,079 root, 21 P1, 14 P2 and 18
P3, with zero skips and zero structural violations. Ruff passed; maintained
typing covered 95 sources and strict typing 35. make format-check passed for
231 Python files. make frontend-check passed console typing/build/326 tests and
P2 source/test typing/build/64 tests. All 95 documents passed and six project
Mermaid diagrams parsed; the invalid syntax fixture was rejected.

Root commands were also tested with temporary failing P2 test/type files: both
failed as required, and both files were removed before final validation. The
expanded Python discovery negative fixture covers P2 and P3 failure propagation.
Offline frozen installs included both dev-only members, without external version
upgrades. Both Dockerfiles rebuilt and eight default transport/auth/M1 checks
passed with the original M1 identity and ten audio frames. An owned nonroot,
network-disabled serving-image probe imported P1 and confirmed P2/P3 development
packages were absent. This smoke does not qualify either new product.

Evidence is retained under .local/validation/p2-p3-foundation/8c0eedd87dc746f5b56d02c3c01becc0.
The complete project acceptance catalogs still contain 17 planned/unregistered
rows each. No paid inference, new business database migration or remote CI ran.
Previous P1 release artifacts remain intact; these new checks are separate.

This completes the controlled P3-A baseline/decision (P3-I01/I02). Actual
background-reasoning quality, remote execution and P3-16 comparison remain later
requirements. Proceed to P3-I03 only after preserving this scoped baseline.
