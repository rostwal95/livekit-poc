# P1 Phase H1 declared inquiry workload baseline

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Implement shared task S-I06 and the first measured contribution to P1-I27
(PLAN-11/21/22, P1-15/18/20 contributions) after the completed
[Phase G gate](0013-p1-phase-g-conversation-and-showcase.md). This slice establishes
an explicit local inquiry workload baseline. It does not complete P1-I27's
restart, slow-provider and media workloads, P1-I26's reusable artifact review,
P1-I28's configured real inference or the P1/whole-portfolio release.

Freeze the versioned workload manifest before any actual measurement. Use the
existing authenticated investigation, scoped case/read/cancel routes, PostgreSQL
v4 authority, installed leased workers and independent synthetic supplier ledger.
Add no production dependency, schema, scheduler, generic handler or model call.
The ordinary M1 stack and its retained task stay unchanged.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| S-I06 / P1-I27 steady baseline | Fresh owned v4 schema, fixed seed and one/two installed workers | Twenty investigations arrive at one per second | Accepted identities and payload bindings remain readable within declared caps | Every admitted investigation has its persisted applicable inquiry result | Actual HTTP/worker run, per-request timing and independent receipts |
| S-I06 / P1-15/18 burst | Same frozen fixture and declared worker modes | Thirty-two distinct offers use bounded HTTP concurrency | No lost accepted identity, overwritten replay or incorrect duplicate inquiry/effect | All thirty-two eligible investigations progress | Raw bounded samples, authority counts and original-key reconciliation |
| S-I06 / P1-18 saturation | Pending cap eight, active cap one, no workers initially | Eight requests are admitted, then twenty-four new requests are attempted | Excess work is rejected before acceptance; original read/replay works at capacity; sampled active work respects one | Admitted investigations progress after workers start | Before/after worker start evidence, acceptance/rejection and supplier counts |
| P1-I23 follow-up | Voice cleanup has actually completed | End finishes successfully | A success notice cannot replace failed/unresolved cleanup | The UI clears its stale Ending notice and displays the observed disconnected state | Existing frontend lifecycle tests/build and actual G regression under this slice |

Expected new-offer totals are declarations: six experiments, 168 offers,
120 accepted investigations and 48 capacity rejections. Replays/reads are separate
calls, not new accepted work. These numbers are not measurement results.

## Interfaces and ownership

The dependency-free harness owns typed immutable WorkloadManifest, Experiment and
ResourceLimits values plus strict manifest/evidence parsing. Local setup owns the
opt-in host runner and isolated container lifecycle. The load controller uses the
existing authenticated HTTP boundary; serving containers use installed application
modules with no checkout bind mount. Only fixture bootstrap receives migration
credentials. Runtime API/workers receive the restricted role and an explicit
UUID-owned schema. PostgreSQL remains the sole acceptance/lease/result authority.

Owned paths are harness/workload_models.py, harness/workloads/p1-inquiry-v1.json,
local-setup/scripts/p1_benchmark.py and focused tests. Shared Makefile, foundation,
AGENTS, setup/validation/design guides are updated with the executable entrypoint.
The small terminal-notice correction belongs to apps/local-console/src/voice.ts;
its readiness, authority and resource-lifetime decisions remain intact.

| Frozen input | V1 declaration |
| --- | --- |
| Seed and modes | 20261109; steady, burst and saturation with one and two workers |
| Requests/concurrency | At most 32 new offers per experiment; steady one HTTP call at a time, other modes at most four; admissions/reads/replays/cancellation share that limit |
| Admission policy | Normal pending64/active4/records1000; saturation pending8/active1/records1000; lease30s |
| Deadlines | 180s per experiment within a 600s overall run; final owned cleanup has a separate bounded 90s budget |
| Container limits | API and each worker: 1000 millicores, 512MiB, pids128; verify actual configured limits |
| Observation policy | Cgroup samples target1s with actual timestamps/cadence; one global round-robin case GET followed by250ms sleep; individual HTTP timeout5s within remaining deadline |
| Evidence bounds | At most4096 raw samples; existing64KiB HTTP envelope; bounded regular nonsymlink manifest/artifacts and fixed safe field vocabularies |
| Statistics | Raw observations and min/median/max; no unsupported small-sample tail percentile or production capacity claim |

Record scheduled offer, actual HTTP start, acknowledgement and first observed
successful inquiry separately. Client-observed result latency includes polling
lag and caller queueing; it is not a precise supplier completion timestamp.
Cgroup memory.current is accounted container memory, not process RSS. CPU usage
units, baseline/deltas, actual cadence, Docker/machine architecture and configured
limits accompany results. Missing observations cannot be replaced with zeros.

Only the test fixture owner creates/upgrades/drops its isolated schema and volumes.
Normal restart semantics and existing user state remain unchanged. If explicit
post-inquiry cancellation is used for cleanup, record its request/disposition,
business state and delivery separately; it is never a successful booking mutation.
Retain accepted-key/result evidence before fixture teardown. Actual supplier apply
calls and mutations must both remain zero.

## Failure cases and validation

Reject duplicate/unknown JSON fields, bool/nonfinite numbers, excessive tasks,
concurrency or samples, incompatible caps, unsafe paths and unknown versions before
process startup. Required unavailable setup, skips, zero useful work, timeouts,
unreadable accepted identities, wrong receipts, extra inquiry/effect, unreaped
children or incomplete owned cleanup fail the run. Retain bounded safe evidence
before cleanup and never revise a budget silently to hide a failed measurement.

Log fixed event/code/role/workload names, finite counts, monotonic elapsed values
and UTC timestamps. Keep credentials, request bodies, raw exceptions, environments
and arbitrary model/content out of logs and artifacts. Correlation identities stay
out of metric labels. HTTP retries retain the original request identity; uncertain
acknowledgement is reconciled rather than counted as rejection or success.

| Gate | Applicable and exact assertion | Prerequisite/resource/time bound | Expected status/evidence |
| --- | --- | --- | --- |
| G-READY | Review and persist immutable manifest/digest before measuring | Owned existing local stack, frozen environment and image | Valid declaration; missing setup fails |
| G-FAST/CONTRACT | Positive and adversarial parser/evidence, deadline, request classification and cleanup fixtures; maintained lint/types/docs | Offline discovery plus declared local socket fixtures only | Nonzero focused/full tests, zero required skips |
| G-DURABLE | All six actual schedules, original-key reconciliation, useful persisted results, independent inquiry count and zero mutation | Installed API/worker containers and isolated PostgreSQL/fixture state | Complete bounded samples and exact observed counts |
| G-OBS | Actual cgroup caps/CPU/memory/pids, finite safe metrics and separate timestamp sources | No fabricated samples or small-sample percentile | Valid resource/timing evidence with measurement limits |
| G-MEDIA regression | Existing actual six-case G gate after terminal-notice change | Matching final host console/assets; preserve closed G artifacts | H regression artifacts and owned cleanup |
| G-PACKAGE/RELEASE | Explicitly incomplete | Genuine consumer/API/artifact review, broader workloads/platforms and configured real inference remain | No full P1 or portfolio pass inferred |

Run affected focused tests, make check, make format-check and make frontend-check.
Validate every changed Design Mermaid view and documentation links. The actual
benchmark command enters onboarding only after its assertions and execution exist.
Store reports under .local/validation/p1-phase-h/ with frozen manifest/source/image
provenance, bounded samples, per-experiment summaries and safe failure records.
Publish a passing aggregate only after independent reconciliation and cleanup.

## Results and handoff

The actual installed-service workload run passed all six experiments on 10 November
2026 (local date), with 3,212 bounded raw observations in 399.669 seconds against
the original 600-second budget. All six independently reconciled and verified
owned cleanup. The declaration was frozen and reviewed before measurement; no
schedule, expected count, resource limit or deadline was changed to obtain a pass.
The closing code/documentation results and their scope are recorded below.

| Actual experiment | New offers | Accepted/results | Explicit capacity rejections | Observed result latency min/median/max, seconds | Experiment elapsed, seconds |
| --- | --- | --- | --- | --- | --- |
| steady-w1 | 20 | 20/20 | 0 | 2.103 / 10.568 / 17.856 | 78.705 |
| steady-w2 | 20 | 20/20 | 0 | 0.786 / 1.628 / 2.311 | 45.622 |
| burst-w1 | 32 | 32/32 | 0 | 10.899 / 46.233 / 56.275 | 123.888 |
| burst-w2 | 32 | 32/32 | 0 | 2.934 / 27.356 / 32.733 | 70.424 |
| saturation-w1 | 32 | 8/8 | 24 | 5.260 / 11.118 / 16.790 | 37.835 |
| saturation-w2 | 32 | 8/8 | 24 | 3.543 / 7.970 / 10.706 | 28.342 |
| Total | 168 | 120/120 | 48 | Separate cohorts; no combined percentile | 399.669 overall, including normal cleanup |

Latency is from scheduled offer to first client-observed validated successful
inquiry and includes shared-slot wait, HTTP and round-robin observation delay.
Saturation also includes deliberate worker startup after admission/rejection.
Experiment elapsed additionally includes preparation and later explicit
cancellation/delivery checks. These clocks and windows answer different questions.
The one-worker modes were slower in this run; worker polling, process startup and
observer lag are included. Controlled profiling/repetition is needed to attribute
cost or claim a general scaling ratio.

Every original accepted key/task/effect/payload and result matched PostgreSQL and
the independent supplier receipt ledger. Both saturation modes retained successful
original reads/replays at full capacity before starting workers. There were zero
lost accepted inquiries, zero supplier apply calls, zero booking mutations and an
unchanged booking revision. After inquiry measurements, 120 explicit cleanup
cancellations and 120 distinct receiver events were independently reconciled;
these are not successful booking changes or human acknowledgement.

The API and each worker had the exact declared one-CPU/512-MiB/128-PID caps, with
positive real cgroup observations and separate cumulative CPU windows. Actual
sequential probe timing/cadence is retained. Probe CPU/accounted-memory/PID costs
and later cancellation/delivery are included; host/controller/VM/shared-PostgreSQL
resource costs are excluded. Samples are current accounted memory, not RSS/peaks.
No missing sample was filled with zero and no small-sample tail percentile was
reported. Supplemental environment metadata records Docker 29.9.2, Linux aarch64,
cgroup v2, 18 logical VM CPUs and 8,317,267,968 VM bytes; the macOS arm64 host had
18 logical CPUs and 25,769,803,776 bytes. This was a shared local machine, with
fresh owned containers/state, rather than an exclusive or cold-machine test.

Implementation review fixed ownership and measurement problems before the run:
preexisting schemas are refused and cleanup requires the exact owner/marker/OID;
lost volume-create acknowledgements remain reconcilable and labels are checked
before mounting; actual bounded migration children are reaped; readiness retries
handle connection startup; missing resource values fail; temporary observed usage
is separate from exact configured limits. First-result source and unknown-attempt
finish are recorded honestly. Failure diagnostics preserve originating fixed
operations and observed numeric process status/timing before temporary capture is
removed, with cleanup failures separate and no raw command/output/environment or
exception content retained. No production schema, dependency or scheduler changed.

Actual evidence is under ignored .local/validation/p1-phase-h:

- declaration-review.json: premeasurement declarations and canonical manifest digest.
- 072518ff56914077b1cb68a613974a13/workload.json, samples.jsonl, summary.json and six
  final experiment reports: frozen input, actual observations, reconciliation,
  source/image provenance and verified cleanup; pre-cleanup measurement snapshots
  retain their distinct non-passing status.
- The same run's environment.json: separately collected shared-host/Docker metadata.
- g-regression-3b1710d3e211481d98ee866270c9b579: six actual browser/native/media
  regression cases passed after the terminal-notice change; all five closed G
  artifacts were restored byte-for-byte. The final screenshot shows Disconnected
  after observed successful media cleanup, while accepted business work remains
  independent. Scripted audio is labelled and real-model quality is unqualified.

| Closing lane | Observed result |
| --- | --- |
| Offline Python/harness | 705 tests, zero skips; structural/source-boundary checks pass |
| Python quality | Lint clean; 75 service/core files typed, three workload/process boundaries strict; 169 files formatted; frozen lock check passes |
| Frontend | 263 tests, strict app/browser-test types and production build pass; existing bundle-size advisory is not a UI latency measurement |
| Installed workload | Six experiments, 120 successful inquiries, 48 explicit rejections, 3,212 raw records, zero lost accepted work/apply calls/mutations; six owned cleanups |
| Independent artifact review | Exact timing/count/concurrency/cap/CPU-window/result/source reconciliation passes across all records; no skipped sample slots observed |
| Browser/native/trace regression | Six cases pass again on the exact frozen workload image; all five closed G artifacts restored byte-for-byte |
| M1/RTC compatibility | Authenticated original-key replay/conflict, named dispatch, UTF-8 text and ten audio frames pass; original retained M1 task identity preserved |
| Documentation and diagrams | 81 documents, zero violations; all 36 views across 12 designs/templates parse, malformed negative rejected |
| Whole acceptance catalog | Exit 2/incomplete as expected: six registered runners pass; 49 product scenarios lack complete runners |

The final-image browser evidence is under
g-regression-final-8e5088b876504e3b9b88eda16108853e, with the same image identity as
the measured workload. Earlier H regression evidence remains retained separately.
The installed core/API and native application source and frozen dependencies were
verified by the actual helpers. No new PostgreSQL suite execution is claimed for
H1: production storage/schema code is unchanged from the closed G 255-test lane;
the H1 workload itself supplies six new actual PostgreSQL/installed-worker runs.
The catalog still registers no new complete charter row.

Final fast validation passed again after the current-instruction cleanup. The
source-bound phase-h1-gate.json aggregate records closure with final documentation,
workload, same-image browser and independent cleanup evidence. A separate read-only
Docker/catalog inspection found no remaining containers, volumes or schemas owned
by this workload run. Phase H1 is complete. The wider Phase H/P1 release remains
incomplete.

This slice uses AI coding assistance and independent AI review. Personal portfolio
claims still require the owner to reproduce and explain the implementation and
its observed limits. Next H slices cover measured restart/slow-provider/media
workloads, genuine-consumer public API/artifact proof and separately configured
real inference. P2/P3 remain planned. Full P1-I27, package/platform/remote-CI and
portfolio release gates remain open.
