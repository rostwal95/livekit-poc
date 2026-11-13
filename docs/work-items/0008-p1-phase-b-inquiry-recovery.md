# P1 Phase B independent inquiry and crash reconciliation

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

After the completed Phase A gate, implement P1-I05 through P1-I07: an independent
persisted read-only fake supplier, one bounded inquiry worker and an actual
supplier-success/before-local-acknowledgement crash. Investigation never mutates
the booking. This completes the first inquiry slice, not the whole P1 release.

| Criterion | Given | When | Safety | Useful progress | Evidence |
| --- | --- | --- | --- | --- | --- |
| P1-04 | Accepted inquiry and separately seeded supplier database | An independent worker process runs once | Supplier booking snapshot remains unchanged; result matches accepted request | Result persists under original workflow/effect | Real process and both SQLite stores |
| P1-05 | Supplier success durably committed; local attempt still running | Kill/reap worker at the named barrier, then start another process | Same effect, one logical supplier inquiry, interrupted old attempt cannot finalize | Reconciliation persists the original result | PID-bound barrier, SIGKILL observation and new worker |
| Replay/limits | Completed execution or saturated cooperative worker | Run again or attempt concurrent admission | No new effect/attempt on terminal replay; lock/caps reject explicitly | Admitted work and stopped-worker recovery progress | Normal, capacity and failure assertions |

## Interfaces and ownership

ExecutionStore retains state/attempt authority; recover_attempt preserves effect
identity with an optimistic version check and finite manual-attempt budget. The
worker holds a cooperative POSIX process lock for its whole single inquiry.
The fake supplier owns separate bookings/inquiries and declares read-only,
idempotency and lookup capabilities. Neither component creates a second durable
execution scheduler. The store lock cannot independently fence an external
supplier; the participating fake supplier's stable-key contract is the proof.

## Failure cases and validation

G-READY requires the Phase A gate. G-CONTRACT covers result binding, scoped keys,
explicit supplier schema initialization and safe typed errors. G-DURABLE uses
actual processes/independent stores/controlled crash plus normal useful progress.
G-OBS inspects safe producer categories and excludes private exception/request
values. G-FAST runs all suites, lint/types/format and documentation. G-MEDIA and
full release/packaging are not claims of this offline phase. Run actual local
container import/execution and foundation smoke when images are rebuilt; preserve
existing data and never reset the live application database.

No automatic retry/backoff/deadline policy, mutating supplier method, PostgreSQL
coordination, distributed lease, conversation/model integration or playback claim
is introduced. Record exact commands, gates, reviews and remaining evidence below.

## Results and handoff

Phase B passed and is complete for P1-I05 through P1-I07. Independent source
review found no remaining blocker after import alignment, hard-link lock guards,
finite manual recovery, correct result binding and safe CLI boundary checks.

Observed verification:

- Full make check: 275 Python tests passed, zero skips and no ResourceWarning in
  retained suite output. Ruff and structural/documentation checks passed. Mypy
  passed for 21 service/core files plus strict checking of the process helper.
  make format-check passed for 58 files.
- Focused evidence includes 20 real-store supplier tests, 15 worker tests, four
  actual independent-worker acceptance scenarios, five recovery-version tests
  and three CLI privacy/defect tests. The final full suite retains all Phase A
  acceptance, migration, async ownership and original foundation checks.
- P1-04/P1-05 run the shared four-test inquiry suite. An actual owned worker was
  killed/reaped after independent supplier success but before local completion;
  a fresh process preserved the effect ID, recovered the original inquiry and
  persisted the result. Exactly one logical inquiry remained, old/new attempts
  were interrupted/succeeded, and the booking snapshot did not change.
- Completed replay creates no additional attempt/effect. Unavailable availability
  is a successful read-only result. Definitive rejection is recorded safely and
  another valid request progresses. External callbacks can write another execution,
  proving the supplier call does not hold the execution transaction.
- Actual local image rebuild/start preserved volumes. From /tmp in the Linux
  container, ten installed application-wheel modules matched host source hashes;
  an independent worker completed, terminal replay retained one attempt/inquiry,
  and safe dispatch/completion/store/supplier JSON events were inspected.
- Container validation exposed missing CLI worker events caused by __main__ logger
  names. Stable qualified logger names and real CLI event assertions fixed it;
  full checks and rebuilt-image verification were repeated successfully. This is
  not a claim that every SDK log shares the application schema.
- Actual RTC smoke passed readiness/authentication, original M1 replay/conflict,
  named dispatch, ordinary/full UTF-8-boundary echo and real audio reception. The
  original pre-change M1 task ID remained unchanged. No reset was performed.
- The documented independent-worker example executed successfully. Documentation
  checked 63 maintained files; all 33 Mermaid diagrams passed real syntax parsing.
  Whitespace checks passed.
- Complete harness result is correctly incomplete, exit 2: BASE-01 and P1-01
  through P1-05 passed; 49 product requirements remain unimplemented. No missing
  case was hidden or converted into a skip.

Retained evidence is .local/validation/p1-phase-b/fast.txt, format.txt,
types.txt, inquiry.txt, supplier.txt, recovery.txt, cli-boundaries.txt, deep.json,
container-probe.json, smoke.json, documented-demo.json, source-manifest.json and
phase-gate.json. The source manifest identifies the final working-tree files,
runtime, backend and offline mode without embedding source identifiers in prose.
AI assisted implementation and separate migration/worker/acceptance reviews.

Next: P1-C, beginning with shared S-I05 and P1-I08/I09. Preserve the first SQLite
proof; introduce controlled PostgreSQL migration/import and restricted runtime
roles before richer case/confirmation/wait/effect semantics. SQLite remains a
bounded cooperating single-worker subset: no distributed leases, arbitrary
workflows, automatic retries/deadlines, booking mutation or conversation/media
adapter. P1-19 backend qualification, installed-library consumer, advertised
Python matrix, real-model/capacity/browser-playback and remote Linux CI gates
remain separate. The container test verifies the installed application wheel,
not a completed separately packaged P1 SDK release.
