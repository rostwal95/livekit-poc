# P1 Phase A schema-safe execution foundation

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P1 Phase A tasks P1-I01 through P1-I04 |
| Audience | Engineers changing P1 SQLite execution, migration or process tests; coding agents |
| Scope | Explicit SQLite migration, typed inquiry and attempt identities, bounded async I/O and process tests; excludes supplier, model, mutation, wait, cancel and lease behavior |
| Owns | Change plan, observed verification and handoff for P1-I01 through P1-I04 |
| Related | [Work item 0006](0006-design-and-engineering-gates.md) · [Work item 0008](0008-p1-phase-b-inquiry-recovery.md) · [SQLite subset decision](../decisions/0002-sqlite-inquiry-subset.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

Implement P1 (Agent Continuity Lab) tasks P1-I01 through P1-I04 from the
[granular roadmap](../implementation-plan.md). They cover build-plan work packages
PLAN-01 and PLAN-02 and the process-test portion of PLAN-03. Preserve M1 (the
original SQLite confirmed-investigation intake) and add explicit migration, typed
persisted inquiry and attempt identities, bounded async I/O and meaningful process
tests. The [decision](../decisions/0002-sqlite-inquiry-subset.md) fixes the
supported subset. No supplier, model, mutation, wait, cancel or lease behavior is
claimed by Phase A.

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-01 | Migrated store and trusted local scope | Child accepts, acknowledges and is actually terminated | Original workflow/payload/effect remain readable | A fresh process inspects it | Owned process records and real SQLite |
| P1-02 | Identical scoped canonical request | Concurrent submissions or killed postcommit/preack child | One logical workflow/effect, no replacement | Original request replays successfully | Concurrent processes and named barrier |
| P1-03 | Existing key/payload | Change payload or scope | Original-scope conflict preserves state | Another scope accepts independently | Store and independent process assertions |
| P1-19 partial | Original queued M1 fixture | Explicit migration, interruption or restore | Original IDs/payload bytes preserved; no serving DDL | Old intake remains readable and upgraded inquiry can progress | Migration/backup/rollback tests |
| Resource/diagnostic contract | Bounded async port and safe CLI | Caller cancel, saturation or invalid state | No leaked I/O slot, private exception or unauthorized state | Eligible calls progress after actual completion | Cancellation, sentinel, timeout and normal tests |

## Interfaces and ownership

| Component | Responsibility |
| --- | --- |
| Existing `continuity_lab` package | Owns the minimal execution subset, without a premature package move |
| Migration | Alone owns data definition language (DDL) |
| `ExecutionStore` | Owns inquiry state and attempt transitions |
| `TaskStore` | Retains intake-only compatibility |
| Explicit enrollment | Bridges later M1 writes |
| Test harness | Owns only its children |

GET never repairs data. `created` and `enrolled` have separate meanings. Version
checks and result-to-request binding protect transitions. They do not provide
external supplier fencing.

## Failure cases and validation

The gate names below are the engineering gates defined in the
[validation plan](../validation-plan.md#engineering-gates-and-acceptance-authoring).

| Gate | Requirement in this phase |
| --- | --- |
| G-READY | Defines the contract above |
| G-FAST | Runs the existing full suite, lint, typing and formatting with new core modules included |
| G-CONTRACT | Checks typed boundaries, canonical conflict, scope, unsupported operations and safe errors |
| G-DURABLE | Uses actual commit, kill and reopen schedules and migration, backup and restore schedules |
| G-OBS | Checks producer events and secret-safe diagnostics |
| G-MEDIA, G-PACKAGE and G-RELEASE | Not Phase A claims; real backend, media and package gates remain pending |

Run focused migration, execution, async and process suites and the actual P1-01,
P1-02 and P1-03 acceptance before registration. Then run the full fast lane and
the original BASE-01 baseline case. Inspect SQLite state and code independently.
Only move to Phase B after the gate passes. Exact commands, outcomes and artifacts
will be recorded after execution.

## Results and handoff

Phase A passed and is complete for P1-I01 through P1-I04. Independent review found
no remaining blocker after adding retained-record saturation and correcting
current capability summaries. Original M1 behavior, investigation-only consent,
identity and payload bytes, and explicit enrollment remain intact.

### Observed gates

Observed verification from the repository frozen interpreter:

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline checks | `make check` | 228 Python tests passed with zero skips; all structural and documentation checks and Ruff passed |
| Typing | Mypy in `make check` | 19 service and core files passed, plus strict checking of the new process helper; legacy imports outside that strict scope unchanged |
| Formatting | `make format-check` | 51 files passed |
| Documentation | Documentation checks | 62 documents checked with zero violations |
| Diagrams | Actual Mermaid parsing | All 33 diagrams passed |
| Focused suites | Focused migration, process and async suites | 15 migration, 18 real-process helper and 12 actual-thread async tests passed, plus the execution, unit and acceptance checks in the full suite |
| Acceptance cases | Individual `harness run` commands | BASE-01, P1-01, P1-02 and P1-03 passed |
| CLI example | Documented `execution_cli` migrate, submit and list example | Passed with safe JSON output and events |
| Complete catalog | Complete catalog result | Incomplete (exit 2): four passing cases including the baseline, and 51 unimplemented product requirements |

The three product registrations run the shared five-assertion-scenario suite.
They do not claim supplier execution or count duplicate suite runs as coverage.
No live application database was migrated or reset. P1-19 SQLite migration
evidence remains partial pending later backend qualification.

### Review corrections

Review corrections include stale-attempt and result binding, canonical
stored-state checks, original exception preservation during async cleanup
timeout, retained admission capacity, strict typing scope and accurate current
documentation. Implementation and review used AI assistance with separate
migration, harness and acceptance reviewers.

### Evidence and next step

Evidence is under `.local/validation/p1-phase-a/`:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast lane output |
| `format.txt` | Format check output |
| `types.txt` | Type check output |
| `process-types.txt` | Strict process-helper type check output |
| `acceptance.json` | Individual acceptance case results |
| `cli-demo.json` | Documented CLI example result |
| `deep.json` | Complete catalog result |

Checks used the frozen Python runtime. An initial unsupported multi-ID harness
invocation was corrected to individual supported commands. A transient local
cache-write issue was rerun under the authorized cache. No dependency version was
changed.

No supplier, worker, media or full release claim is made. Proceed to Phase B,
P1-I05 through P1-I07, only now that the gate has passed.
