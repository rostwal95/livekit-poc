# P1 Phase H2 restart and slow-supplier workloads

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Complete the next P1-I27/S-I06 inquiry reliability contribution after the closed
H1 baseline. Add four explicitly declared cases: restart and slow-shutdown, each
with one and two workers. Each offers 32 new identities against pending8/active1:
eight accepted, twenty-four rejected before acceptance. A RESERVED supplier lock
permits lookup/metadata reads and prevents the real inquiry write while scoped HTTP
inspection/replay are timed. The restart schedule kills API/workers with accepted
pending/active work, observes all stopped, then starts the same owned state. The
slow-shutdown schedule injects at least one second of supplier delay while workers
drain under SIGTERM, then restarts. Every accepted inquiry must complete under its
original identity/effect/deadline and independently reconcile with supplier truth.
No model call, production fault endpoint, schema or second queue is introduced.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-I27 / P1-18 restart | Eight admitted, active1 and excess rejected | API and one/two workers are killed and restarted | All old processes observed stopped; original requests/deadlines preserved | All eight inquiries and later explicit cancellation deliveries reconcile | Actual installed Docker/PostgreSQL/independent supplier, frozen schedule |
| P1-I27 / P1-18 slow supplier and drain | Real supplier write is blocked, queue at capacity | Scoped read/replay and SIGTERM occur | Controls do not await supplier; finite owned shutdown and separate CPU epochs | Original work progresses after release/restart without a duplicate effect | Actual lock, HTTP timing, process states and independent receipts |

## Interfaces and ownership

The dependency-free reliability manifest references the unchanged H1 canonical
manifest digest, which supplies existing resource, request, sampling and cleanup
bounds. H2 fault identities stay in their own case directories; underlying raw
HTTP/resource records explicitly retain the existing burst schedule identity.
The host controller reuses installed-service H1 lifecycle/HTTP primitives, with
new fault control and segmented resource observation. Product imports and runtime
state remain authoritative. The package extraction in the separate I26 slice may
change source locations while retaining import names and stored formats; every
actual run must verify the installed source against the final canonical source.

The versioned declaration owns 600 seconds overall, 180 per case, at most4096 raw
records, four HTTP slots, API/each worker one CPU/512MiB/pids128, lease30s, and
existing90s owned cleanup. Real supplier lock is bounded4.5s against its existing5s
storage timeout. Read+replay controls have a combined1.5s deadline. Slow-shutdown
holds the supplier for at least1s after observing the actual worker
health become not-ready with an active child during SIGTERM drain; worker Docker grace10s,
API grace5s and the observed whole stop phase must remain within30s. Declared
128 new offers/32 accepted/96 rejected are inputs, not measurements.

## Failure cases and validation

Reject duplicate/unknown/nonfinite/boolean/unsafe declarations and changed base
digests before execution. Real missing setup, failed barriers, expired lock,
missing useful results, unsafe replay, wrong receipt, resource absence, unreaped
children, unowned resources or incomplete cleanup fail without rewriting budgets.
Preserve private capture only until closed fixed-code failure records are saved.
Keep original failure and cleanup failure separate; no argv/credentials/payloads,
raw stdout/stderr or dependency exception chains enter retained diagnostics.
Cgroup CPU counters reset at restart: separate raw files and CPU windows prevent
subtracting unrelated lifetimes. Require at least two samples and a positive
observed CPU window per serving role in each epoch. Collect the two idle baseline
samples before acquiring the bounded supplier lock; pre-fault resources include
that declared idle baseline. Retain validated before/stopped/restarted process
PID/start/exit observations and original/final deadline/epoch snapshots, rather
than only success flags. Graceful schedules require worker exit0 and API exit143: the pinned Uvicorn
server deliberately re-raises SIGTERM after completing lifespan shutdown. Require
exactly one completed-application-shutdown and finished-server-process event from
bounded private logs before accepting that API exit. Missing, duplicate or failed
shutdown markers cannot pass. Crash schedules require observed SIGKILL exit137. Accounted memory is not RSS or a peak. Shared host,
VM and database costs are excluded; probe/cancellation/delivery costs are included.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Freeze declarations before measurement | Immutable strict manifest and unchanged base digest | No Docker load during planning | Reviewed declaration, not_started planning |
| G-FAST/CONTRACT | Parser, ownership and fault controller | Adversarial declarations, bounded samples, real local SQLite barrier and safe failures | Offline tests, maintained strict typing/lint/format | Nonzero tests, zero skips |
| G-DURABLE/OBS | Four actual fault schedules | Active/pending pressure, stable identity/deadline, independent receipt/no mutation, positive segmented resources | Owned installed containers/PostgreSQL/fixture locks | Passing measurements only after owned cleanup |
| G-MEDIA | Separately qualified next contribution | Declared browser/audio responsiveness alongside work | Actual WebRTC and frozen media workload | Not covered by these inquiry-only cases |
| G-PACKAGE/RELEASE | Separate I26/I28 and acceptance gates | Genuine wheel consumer, real inference, supported platform and whole P1 | No partial case registration or release inference | Explicit incomplete until all assertions exist |

## Results and handoff

Completed the four declared inquiry reliability cases on the final installed
Python image. The immutable summary is
.local/validation/p1-phase-h2/f7b22f76fb90410382280995a532d303/summary.json.
The run took214.802s and retained1,473 bounded observations:128 offers,
32 accepted,96 rejected,32 independently reconciled inquiry results and32 receiver
events. Lost accepted work, supplier apply calls and booking mutations were all0.
Every case verified owned cleanup and preserved original request/deadline identity.
Scoped read/replay controls took0.061–0.172s; observed stop took0.568–1.877s.
These are four observed schedules, not production-capacity estimates.

Both crash cases observed all serving exits137 and fresh restarted lifetimes.
Both graceful cases observed worker exit0, API exit143, exactly one completed
lifespan/finished-process marker, and not-ready/active-child drain before the
minimum supplier release delay. Pre/post CPU windows have distinct origins.
An independent read-only audit passed121 cross-checks across the H2 and package
artifacts. It recomputed raw admission/result totals and current source bindings;
independent receipt-row/log checks were performed live by the bounded producer.
The summary does not separately retain raw supplier rows or private shutdown logs.

Validation:15 focused reliability tests, strict controller typing, the real four-case
run and full shared fast validation passed. The latter ran891 Python tests across
the21 package and870 root tests, with zero required skips; lint and21 strict
sources passed, with205 files formatted. Other P1 media/release work remains
separate. Retain the first failed full run and focused investigation: they exposed
the incorrect all-processes-exit0 assumption; the corrected assertion additionally
requires actual Uvicorn lifespan completion under the unchanged budgets.
