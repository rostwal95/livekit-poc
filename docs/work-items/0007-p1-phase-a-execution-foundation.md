# P1 Phase A schema-safe execution foundation

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Implement P1-I01 through P1-I04 (PLAN-01/02 and the process-test portion of
PLAN-03). Preserve M1 and add explicit migration, typed persisted inquiry/attempt
identities, bounded async I/O and meaningful process tests. The
[decision](../decisions/0002-sqlite-inquiry-subset.md) fixes the supported subset.
No supplier, model, mutation, wait/cancel or lease behavior is claimed by Phase A.

| Criterion | Given | When | Safety assertion | Useful progress | Evidence |
| --- | --- | --- | --- | --- | --- |
| P1-01 | Migrated store and trusted local scope | Child accepts, acknowledges and is actually terminated | Original workflow/payload/effect remain readable | A fresh process inspects it | Owned process records and real SQLite |
| P1-02 | Identical scoped canonical request | Concurrent submissions or killed postcommit/preack child | One logical workflow/effect, no replacement | Original request replays successfully | Concurrent processes and named barrier |
| P1-03 | Existing key/payload | Change payload or scope | Original-scope conflict preserves state | Another scope accepts independently | Store and independent process assertions |
| P1-19 partial | Original queued M1 fixture | Explicit migration, interruption or restore | Original IDs/payload bytes preserved; no serving DDL | Old intake remains readable and upgraded inquiry can progress | Migration/backup/rollback tests |
| Resource/diagnostic contract | Bounded async port and safe CLI | Caller cancel, saturation or invalid state | No leaked I/O slot, private exception or unauthorized state | Eligible calls progress after actual completion | Cancellation, sentinel, timeout and normal tests |

## Interfaces and ownership

The existing continuity_lab package owns the minimal execution subset without a
premature package move. Migration alone owns DDL. ExecutionStore owns inquiry
state/attempt transitions; TaskStore retains intake-only compatibility. Explicit
enrollment bridges later M1 writes; GET never repairs data. created and enrolled
have separate meanings. Version checks and result/request binding protect
transitions, not external supplier fencing. The test harness owns only its children.

## Failure cases and validation

G-READY defines the contract above. G-FAST runs the existing full suite, lint,
typing and formatting with new core modules included. G-CONTRACT checks typed
boundaries, canonical conflict, scope, unsupported operations and safe errors.
G-DURABLE uses actual commit/kill/reopen and migration/backup/restore schedules.
G-OBS checks producer events and secret-safe diagnostics. G-MEDIA/G-PACKAGE and
G-RELEASE are not Phase A claims; real backend/media/package gates remain pending.

Run focused migration/execution/async/process suites and actual P1-01/02/03
acceptance before registration, then full fast and original BASE-01. Inspect
SQLite state and code independently; only move to Phase B after the gate passes.
Exact commands/outcomes and artifacts will be recorded after execution.

## Results and handoff

Phase A passed and is complete for P1-I01 through P1-I04. Independent review
found no remaining blocker after adding retained-record saturation and correcting
current capability summaries. Original M1 behavior, investigation-only consent,
identity/payload bytes and explicit enrollment remain intact.

Observed verification from the repository frozen interpreter:

- make check: 228 Python tests passed, zero skips; all structural/doc checks and
  Ruff passed. Mypy passed for 19 service/core files plus strict checking of the
  new process helper, with unchanged legacy imports outside that strict scope.
- make format-check: 51 files passed. Documentation checked 62 documents with
  zero violations. Actual Mermaid parsing passed all 33 diagrams.
- Focused suites passed 15 migration, 18 real-process helper, 12 actual-thread
  async and the execution/unit/acceptance checks in the full suite.
- Individual harness run BASE-01, P1-01, P1-02 and P1-03 commands passed.
  The three product registrations run the shared five-assertion-scenario suite;
  they do not claim supplier execution or count duplicate suite runs as coverage.
- Documented execution_cli migrate/submit/list example passed with safe JSON
  output/events. No live application database was migrated or reset.
- Complete catalog result remains incomplete, exit 2: four passing cases including
  the baseline, 51 unimplemented product requirements. P1-19 SQLite migration
  evidence remains partial pending later backend qualification.

Evidence: .local/validation/p1-phase-a/fast.txt, format.txt, types.txt,
process-types.txt, acceptance.json, cli-demo.json and deep.json. Checks used the
frozen Python runtime; an initial unsupported multi-ID harness invocation was
corrected to individual supported commands. A transient local cache-write issue
was rerun under the authorized cache; no dependency version was changed.

Review corrections include stale-attempt/result binding, canonical stored-state
checks, original exception preservation during async cleanup timeout, retained
admission capacity, strict typing scope and accurate current documentation.
Implementation and review used AI assistance with separate migration, harness
and acceptance reviewers. No supplier/worker/media or full release claim is made.
Proceed to Phase B, P1-I05 through P1-I07, only now that the gate has passed.
