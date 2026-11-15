# P1 Phase B independent inquiry and crash reconciliation

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P1 Phase B tasks P1-I05 through P1-I07 |
| Audience | Engineers changing the P1 inquiry worker, fake supplier or crash recovery; coding agents |
| Scope | Read-only fake supplier, one bounded inquiry worker and crash reconciliation; excludes PostgreSQL coordination, leases, automatic retries, mutation and media |
| Owns | Change plan, observed verification and handoff for P1-I05 through P1-I07 |
| Related | [Work item 0007](0007-p1-phase-a-execution-foundation.md) · [Work item 0009](0009-p1-phase-c-postgres-cutover.md) · [SQLite subset decision](../decisions/0002-sqlite-inquiry-subset.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

After the completed Phase A gate, implement P1 (Agent Continuity Lab) tasks
P1-I05 through P1-I07 from the [granular roadmap](../implementation-plan.md). They
add an independent persisted read-only fake supplier, one bounded inquiry worker
and an actual crash after supplier success but before local acknowledgement.
Investigation never mutates the booking. This completes the first inquiry slice,
not the whole P1 release.

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-04 | Accepted inquiry and separately seeded supplier database | An independent worker process runs once | Supplier booking snapshot remains unchanged; result matches accepted request | Result persists under original workflow/effect | Real process and both SQLite stores |
| P1-05 | Supplier success durably committed; local attempt still running | Kill/reap worker at the named barrier, then start another process | Same effect, one logical supplier inquiry, interrupted old attempt cannot finalize | Reconciliation persists the original result | PID-bound barrier, SIGKILL observation and new worker |
| Replay/limits | Completed execution or saturated cooperative worker | Run again or attempt concurrent admission | No new effect/attempt on terminal replay; lock/caps reject explicitly | Admitted work and stopped-worker recovery progress | Normal, capacity and failure assertions |

## Interfaces and ownership

| Component | Responsibility |
| --- | --- |
| `ExecutionStore` | Retains state and attempt authority |
| `recover_attempt` | Preserves effect identity with an optimistic version check and a finite manual-attempt budget |
| Worker | Holds a cooperative POSIX process lock for its whole single inquiry |
| Fake supplier | Owns separate bookings and inquiries; declares read-only, idempotency and lookup capabilities |

Neither the worker nor the fake supplier creates a second durable execution
scheduler. The store lock cannot independently fence an external supplier. The
participating fake supplier's stable-key contract is the proof.

## Failure cases and validation

The gate names below are the engineering gates defined in the
[validation plan](../validation-plan.md#engineering-gates-and-acceptance-authoring).

| Gate | Requirement in this phase |
| --- | --- |
| G-READY | Requires the Phase A gate |
| G-CONTRACT | Covers result binding, scoped keys, explicit supplier schema initialization and safe typed errors |
| G-DURABLE | Uses actual processes, independent stores and a controlled crash, plus normal useful progress |
| G-OBS | Inspects safe producer categories and excludes private exception and request values |
| G-FAST | Runs all suites, lint, types, format and documentation checks |
| G-MEDIA, full release and packaging | Not claims of this offline phase |

Run actual local container import and execution and foundation smoke when images
are rebuilt. Preserve existing data and never reset the live application
database.

No automatic retry, backoff or deadline policy, mutating supplier method,
PostgreSQL coordination, distributed lease, conversation or model integration, or
playback claim is introduced. Record exact commands, gates, reviews and remaining
evidence below.

## Results and handoff

Phase B passed and is complete for P1-I05 through P1-I07. Independent source
review found no remaining blocker after import alignment, hard-link lock guards,
finite manual recovery, correct result binding and safe CLI boundary checks.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline checks | Full `make check` | 275 Python tests passed, with zero skips and no ResourceWarning in retained suite output; Ruff and structural and documentation checks passed |
| Typing | Mypy | 21 service and core files passed, plus strict checking of the process helper |
| Formatting | `make format-check` | 58 files passed |
| Installed container | Actual local image rebuild and start | Volumes preserved; from /tmp in the Linux container, ten installed application-wheel modules matched host source hashes |
| RTC smoke | Actual real-time communication (RTC) smoke | Passed readiness and authentication, original M1 replay and conflict, named dispatch, ordinary and full UTF-8-boundary echo and real audio reception |
| Documented example | Independent-worker example | Executed successfully |
| Documentation | Documentation checks | 63 maintained files checked |
| Diagrams | Real Mermaid syntax parsing | All 33 diagrams passed |
| Whitespace | Whitespace checks | Passed |
| Complete harness | Complete harness result | Correctly incomplete (exit 2): BASE-01 and P1-01 through P1-05 passed, and 49 product requirements remain unimplemented |

Observation details:

- Focused evidence includes 20 real-store supplier tests, 15 worker tests, four
  actual independent-worker acceptance scenarios, five recovery-version tests and
  three CLI privacy and defect tests. The final full suite retains all Phase A
  acceptance, migration, async ownership and original foundation checks.
- P1-04 and P1-05 run the shared four-test inquiry suite. An actual owned worker
  was killed and reaped after independent supplier success but before local
  completion. A fresh process preserved the effect ID, recovered the original
  inquiry and persisted the result. Exactly one logical inquiry remained. The old
  attempt was interrupted and the new attempt succeeded, and the booking snapshot
  did not change.
- Completed replay creates no additional attempt or effect. Unavailable
  availability is a successful read-only result. Definitive rejection is recorded
  safely, and another valid request progresses. External callbacks can write
  another execution, proving the supplier call does not hold the execution
  transaction.
- In the rebuilt container, an independent worker completed, terminal replay
  retained one attempt and inquiry, and safe dispatch, completion, store and
  supplier JSON events were inspected.
- Container validation exposed missing CLI worker events caused by `__main__`
  logger names. Stable qualified logger names and real CLI event assertions fixed
  it. Full checks and rebuilt-image verification were repeated successfully. This
  is not a claim that every SDK log shares the application schema.
- The original pre-change M1 task ID remained unchanged (M1 is the original SQLite
  confirmed-investigation intake). No reset was performed.
- No missing harness case was hidden or converted into a skip.

### Evidence and next step

Retained evidence is under `.local/validation/p1-phase-b/`:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast lane output |
| `format.txt` | Format check output |
| `types.txt` | Type check output |
| `inquiry.txt` | Inquiry suite output |
| `supplier.txt` | Supplier suite output |
| `recovery.txt` | Recovery suite output |
| `cli-boundaries.txt` | CLI boundary suite output |
| `deep.json` | Complete harness result |
| `container-probe.json` | Installed container probe |
| `smoke.json` | RTC smoke result |
| `documented-demo.json` | Documented independent-worker example |
| `source-manifest.json` | Final working-tree files, runtime, backend and offline mode |
| `phase-gate.json` | Phase gate result |

The source manifest identifies the final working-tree files, runtime, backend and
offline mode without embedding source identifiers in prose. AI assisted
implementation and separate migration, worker and acceptance reviews.

Next: P1 Phase C (P1-C), beginning with shared task S-I05 and P1-I08 and P1-I09.
Preserve the first SQLite proof. Introduce controlled PostgreSQL migration and
import and restricted runtime roles before richer case, confirmation, wait and
effect semantics. SQLite remains a bounded cooperating single-worker subset: no
distributed leases, arbitrary workflows, automatic retries or deadlines, booking
mutation, or conversation or media adapter.

P1-19 backend qualification, the installed-library consumer, the advertised Python
matrix, real-model, capacity and browser-playback gates, and remote Linux CI gates
remain separate. The container test verifies the installed application wheel, not
a completed separately packaged P1 SDK release.
