# P1 Phase H2 restart and slow-supplier workloads

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the declared restart and slow-supplier inquiry workloads, their gates and their observed results |
| Audience | Engineers changing P1 worker shutdown, restart, supplier timeouts or workload tooling; reviewers; coding agents |
| Scope | Four Phase H2 inquiry fault schedules for P1-I27 and S-I06; excludes media, package and release gates |
| Owns | Phase H2 change plan, observed verification and handoff |
| Related | [Phase H1 work item](0014-p1-phase-h-workload-baseline.md) · [Package work item](0016-p1-standalone-package.md) · [Release work item](0019-p1-phase-h-release-qualification.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

Complete the next inquiry reliability contribution to P1 (Agent Continuity Lab)
task P1-I27 and shared task S-I06 after the closed
[Phase H1 baseline](0014-p1-phase-h-workload-baseline.md). Add four explicitly
declared cases: restart and slow-shutdown, each with one and two workers. Each case
offers 32 new identities against a pending cap of eight and an active cap of one:
eight are accepted and twenty-four are rejected before acceptance.

A RESERVED supplier lock permits lookup and metadata reads and prevents the real
inquiry write while scoped HTTP inspection and replay are timed. The restart
schedule kills the API and workers with accepted pending and active work, observes
that all have stopped, then starts the same owned state. The slow-shutdown
schedule injects at least one second of supplier delay while workers drain under
SIGTERM, then restarts.

Every accepted inquiry must complete under its original identity, effect and
deadline and independently reconcile with supplier truth. No model call,
production fault endpoint, schema or second queue is introduced.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I27 / P1-18 restart | Eight admitted, active cap one and excess rejected | API and one/two workers are killed and restarted | All old processes observed stopped; original requests/deadlines preserved | All eight inquiries and later explicit cancellation deliveries reconcile | Actual installed Docker/PostgreSQL/independent supplier, frozen schedule |
| P1-I27 / P1-18 slow supplier and drain | Real supplier write is blocked, queue at capacity | Scoped read/replay and SIGTERM occur | Controls do not await supplier; finite owned shutdown and separate CPU epochs | Original work progresses after release/restart without a duplicate effect | Actual lock, HTTP timing, process states and independent receipts |

## Interfaces and ownership

The dependency-free reliability manifest references the unchanged H1 canonical
manifest digest, which supplies existing resource, request, sampling and cleanup
bounds. H2 fault identities stay in their own case directories. Underlying raw
HTTP and resource records explicitly retain the existing burst schedule identity.
The host controller reuses installed-service H1 lifecycle and HTTP primitives,
with new fault control and segmented resource observation. Product imports and
runtime state remain authoritative.

The package extraction in the separate P1-I26 slice may change source locations
while retaining import names and stored formats. Every actual run must verify the
installed source against the final canonical source.

The versioned declaration owns these bounds:

| Limit | Value |
| --- | --- |
| Overall run | 600 seconds |
| Each case | 180 seconds |
| Raw records | At most 4096 |
| HTTP slots | Four |
| API and each worker | One CPU, 512 MiB and a PID limit of 128 |
| Leases | 30 seconds |
| Owned cleanup | The existing 90 seconds |

The fault schedules use these bounds:

| Limit | Value |
| --- | --- |
| Real supplier lock | 4.5 s, against its existing 5 s storage timeout |
| Read and replay controls | Combined 1.5 s deadline |
| Slow-shutdown supplier hold | At least 1 s after observing the actual worker health become not-ready with an active child during SIGTERM drain |
| Worker Docker grace | 10 s |
| API grace | 5 s |
| Stop phase | Both graces and the observed whole stop phase must remain within 30 s |
| Declared offers | 128 new offers, 32 accepted and 96 rejected; inputs, not measurements |

## Failure cases and validation

Reject duplicate, unknown, nonfinite, boolean or unsafe declarations and changed
base digests before execution. Real missing setup, failed barriers, an expired
lock, missing useful results, unsafe replay, a wrong receipt, resource absence,
unreaped children, unowned resources or incomplete cleanup fail without rewriting
budgets. Preserve private capture only until closed fixed-code failure records are
saved. Keep the original failure and cleanup failure separate. No argv,
credentials, payloads, raw stdout or stderr, or dependency exception chains enter
retained diagnostics.

Cgroup CPU counters reset at restart. Separate raw files and CPU windows prevent
subtracting unrelated lifetimes. Require at least two samples and a positive
observed CPU window per serving role in each epoch. Collect the two idle baseline
samples before acquiring the bounded supplier lock. Pre-fault resources include
that declared idle baseline. Retain validated PID, start and exit observations for
the before, stopped and restarted processes, and original and final deadline and
epoch snapshots, rather than only success flags.

Each schedule type requires these observed process exits:

| Schedule | Required exits | Additional requirement |
| --- | --- | --- |
| Graceful | Worker exit 0 and API exit 143 | Exactly one completed-application-shutdown and finished-server-process event from bounded private logs before accepting that API exit |
| Crash | Observed SIGKILL exit 137 | None |

The pinned Uvicorn server deliberately re-raises SIGTERM after completing
lifespan shutdown. Missing, duplicate or failed shutdown markers cannot pass.
Accounted memory is not resident set size (RSS) or a peak. Shared host,
virtual machine (VM) and database costs are excluded. Probe, cancellation and
delivery costs are included.

The gate names in this table are the engineering gates defined in the
[validation plan](../validation-plan.md#engineering-gates-and-acceptance-authoring).

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Freeze declarations before measurement | Immutable strict manifest and unchanged base digest | No Docker load during planning | Reviewed declaration, not_started planning |
| G-FAST/CONTRACT | Parser, ownership and fault controller | Adversarial declarations, bounded samples, real local SQLite barrier and safe failures | Offline tests, maintained strict typing/lint/format | Nonzero tests, zero skips |
| G-DURABLE/OBS | Four actual fault schedules | Active/pending pressure, stable identity/deadline, independent receipt/no mutation, positive segmented resources | Owned installed containers/PostgreSQL/fixture locks | Passing measurements only after owned cleanup |
| G-MEDIA | Separately qualified next contribution | Declared browser/audio responsiveness alongside work | Actual WebRTC and frozen media workload | Not covered by these inquiry-only cases |
| G-PACKAGE/RELEASE | Separate P1-I26/P1-I28 and acceptance gates | Genuine wheel consumer, real inference, supported platform and whole P1 | No partial case registration or release inference | Explicit incomplete until all assertions exist |

## Results and handoff

Completed the four declared inquiry reliability cases on the final installed
Python image. The immutable summary is
`.local/validation/p1-phase-h2/f7b22f76fb90410382280995a532d303/summary.json`.

| Measure | Observed result |
| --- | --- |
| Run duration | 214.802 s |
| Bounded observations retained | 1,473 |
| Offers | 128: 32 accepted and 96 rejected |
| Independently reconciled inquiry results | 32 |
| Receiver events | 32 |
| Lost accepted work, supplier apply calls and booking mutations | 0 each |
| Scoped read and replay controls | 0.061–0.172 s |
| Observed stop | 0.568–1.877 s |

Every case verified owned cleanup and preserved original request and deadline
identity. These are four observed schedules, not production-capacity estimates.

Both crash cases observed exit 137 for all serving processes and fresh restarted
lifetimes. Both graceful cases observed worker exit 0, API exit 143, exactly one
completed-lifespan and finished-process marker, and not-ready, active-child drain
before the minimum supplier release delay. CPU windows before and after the fault
have distinct origins.

An independent read-only audit passed 121 cross-checks across the H2 and package
artifacts. It recomputed raw admission and result totals and current source
bindings. Independent receipt-row and log checks were performed live by the
bounded producer. The summary does not separately retain raw supplier rows or
private shutdown logs.

| Check | Observed result |
| --- | --- |
| Focused reliability tests | 15 tests passed |
| Controller typing | Strict typing passed |
| Real four-case run | Passed |
| Full shared fast validation | Passed: 891 Python tests across the 21 package and 870 root tests, with zero required skips |
| Lint, strict typing and formatting | Lint and 21 strict sources passed, with 205 files formatted |

Other P1 media and release work remains separate.

Retain the first failed full run and focused investigation. They exposed the
incorrect assumption that all processes exit 0. The corrected assertion
additionally requires actual Uvicorn lifespan completion under the unchanged
budgets.
