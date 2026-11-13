# Bounded channel workloads and image evidence

Status: Completed
Last reviewed: 12 November 2026

## Behavior and scope

Implement P2-I19's seeded capacity/dormancy experiments and the selected P3-I16
`booking.extract_document` capability after the [completed case restoration and
standalone phase](0038-case-rehydration-and-standalone-release.md). The
[P2 plan](../implementation/p2-channel-continuity.md),
[P3 plan](../implementation/p3-delegation-reliability.md), project charters,
[shared design](../../Design.md) and [validation authority](../validation-plan.md)
own the requirements. Contributions are P2-13/P2-14 and P3-11/P3-15; task
completion alone does not register a complete charter row.

Before edits, the closed checkpoint's 1,535 artifact hashes and all 734 current
public source hashes matched. Preserve qualified P1, its 77 runtime payloads,
original M1, default services/UI, dependencies, locks and image pins. Validation
uses local PostgreSQL/SFU and scripted synthetic adapters. No provider/private-CA
configuration is read and no paid inference, publication or remote CI is required.

P2 must measure real admission, queueing, useful processing, retained identity,
shutdown/restart and many dormant conversations. Declare schedules, seeds,
resources and numeric budgets before measurement. Resource/latency samples and
independent durable reconciliation must support reported outcomes; no extrapolated
production capacity or per-instance limit presented as deployment-wide capacity.
A held telemetry observer must not accumulate unbounded work. First retain the
current failure regression, then fix the bounded notification behavior.

P3 adds a narrow typed image request/result, scoped immutable PNG source resolution,
a bounded read-only handler, structured extracted fields/supporting regions and
explicit missing/conflicting clarification. Retain separate structural-validation
and known-fixture factual-evaluation results. The scripted image provider is a
controlled fixture, not OCR or general vision inference. Input images and text are
untrusted data and grant no tools, consent, notification or mutation authority.

P1 currently accepts only the policy work operation. The new image handler's HTTP
computation is not P1 durable image acceptance/execution. A later reviewed versioned
operation extension is required before composing image work into that coordinator;
never disguise image work as policy work or add another execution queue. Native P1
revision0 continuation remains a separate versioned cross-language prerequisite.
P2-I20's joined operations UI and P3-I17's fixed-policy extension follow separately.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2-13 contribution | Frozen steady/burst/saturation offers and configured limits | Drive the actual verified intake/gateway and bounded processing adapters | Explicit preacceptance rejection/defer, finite live work, zero lost accepted items and exact original identities | Every admitted item stays inspectable and eligible work in both admitted scopes progresses | Real PG, public HTTP, independent SQL/operation observations and raw monotonic samples |
| P2-14 contribution | Many persisted dormant conversations | Observe idle state then resume a selected case | No per-case room/agent/process and no hidden dormant polling loop | Selected current work resumes with original history | Actual durable rows, process/resource observations and scoped SFU read |
| P2 retention/restart | Accepted/replayed/pruned-display inputs and an owned gateway | Shutdown/restart and late equal/changed-body replay | Display pruning cannot remove receipt/key/conflict protection; ownership settles before replacement | Original accepted work is recoverable and progresses | Independent process/PID, durable snapshots and receiver/operation joins |
| P2 telemetry | Held/rejected injected notification promises | Admit/inspect/replay beyond the sink bound | Notification tasks remain finite and diagnostics are body/secret safe | Intake/processing continue despite telemetry failure | Prechange regression, bounded runtime metrics and actual progress |
| P3-11/P3-15 contribution | Scoped accepted source fingerprint and immutable PNG bytes | Invoke the image capability using public typed HTTP | Reject inaccessible/swapped/altered/oversized/excess-dimension/invalid images before provider work | A grounded complete fixture returns useful structured fields | Cross-language fixtures, actual socket path and independent expected facts |
| P3 clarification | Missing, ambiguous or adversarial source text | Validate a schema-valid provider candidate | Wrong values/regions/source bindings fail factual evaluation; instructions remain data | Explicit clarification preserves uncertainty; a later grounded fixture succeeds | Separate structural/factual outcomes, provider call counts and source digests |
| P3 lifecycle/package | Bounded provider, callers, service and built artifacts | Cancel/expire/close, install and run the public consumer | Retain actual work through waiter abandonment; no checkout injection or hidden setup | Capacity returns after actual settlement and a new valid request progresses | Public client/server negative/liveness tests and isolated installed consumer |

## Interfaces and ownership

P2 owns the versioned workload declaration/model, project fixtures, ordinary inbox
notification fix if the baseline confirms it, workload orchestration and tests.
Keep v7 persisted data and existing public receipt/history/dispatch semantics;
introduce no runtime DDL, new scheduler, room-per-case requirement or arbitrary cap
increase to make a workload pass. Existing operation/pool limits are per instance.

P3 owns the new discriminated image codec/handler/provider/evidence boundary and
public Python/TypeScript consumers. Preserve canonical policy wire bytes and the
old default policy behavior. Share the existing bounded authenticated HTTP and
permission/lifetime contract through a reviewed additive interface; keep source
resolution local and trusted, with no arbitrary URL fetch. PNG guard scope and
supported forms must be explicit and linked to the public specification.

Root owns this work item, protocol/API review, shared discovery/Make/type wiring,
independent contract/proof checks, broad verification and the closed checkpoint.
Independent reviewers record authored components honestly. Hold actual PG/SFU lanes
serially. Each producer freezes exact modes, case inventory, sources, role-closed
environments, proof schema/caps and cleanup before a normal measurement.

## Failure cases and validation

The bounds below are initial planning ceilings. Exact approved protocols are
retained before implementation/normal measurement; any reviewed revision is
explicit and never retroactively relabels a failed measurement as passing.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Both substantial slices | Approved interface, complete named inventory, workload seed/budgets, source/authority/cleanup contracts | Closed prior baseline plus retained producer protocols and independent review | No normal execution before the final protocol/source freeze |
| G-FAST/G-CONTRACT | New runtime/contracts/tooling | Positive, malformed, byte/depth/scope, replay, cancellation, observer and useful-progress tests in maintained discovery | Existing frozen Python/Node; no new dependency without reviewed need | Full fast/frontend/typing/format/docs and Mermaid syntax checks pass with no required skips |
| P2 G-DURABLE/workload | Real backlog, restart, retention and dormancy | Steady/burst/saturation, slow adapter, second admitted scope, actual shutdown/restart, held telemetry, original replay/conflict and independent reconciliation | Initially at most 360 seconds including 20 cleanup, 32 children, 16 MiB retained artifacts, 2 MiB per direct proof and 32 KiB report; final sample/schedule limits frozen before measurement | Finite truthful resource/latency samples, zero lost accepted work/duplicate logical operation, useful current progress and owned cleanup |
| P3 G-CONTRACT/G-OBS | Image source/provider/result boundary | Cross-language canonical output and structural/factual separation; invalid/forged/swapped/uncertain/adversarial sources; lifecycle and safe diagnostics | Existing 16 KiB request/8 KiB result, at most four 2 MiB sources, dimension ceiling2048; existing HTTP limits stay fixed | Exact actual error codes, provider-call fences, finite metrics and later useful progress |
| P3 G-PACKAGE | New public consumer | Fresh current artifacts, isolated public image consumer and preserved policy behavior | Initially at most 360 seconds including 20 cleanup, 32 children, 2 MiB aggregate capture and 32 KiB report; no PG claim from socket/package checks | Actual installed product imports/types/source parity and complete cleanup |
| Compatibility | Existing intake/dispatch/native/rehydration/policy paths | Source-bound affected backend/browser/installed regression selection, plus ordinary stack doctor/smoke | Serial local service lanes with exact old reports preserved | No regression or silently broadened authority/inference claims |
| Final handoff | Local POC scope | Independent API/evidence review, current source index, exact physical artifact manifest, prior checkpoint rehash, residual resource checks and original M1 preservation | Private0700 directories/regular0600 files; zero unknown owned children before dependent DDL/file removal | Selected scope completed only after all required gates pass |

Use fixed safe exception codes and finite event/operation/code/outcome metric
labels. Record real counts, byte units, monotonic durations, occupancy and drops;
never put accounts/cases/prompts/image bodies/source URLs/token values in labels
or logs. Sink exceptions remain contained. Timeout/cancellation does not prove
provider or thread stop. Preserve primary failure, actual owners and private work
until resources settle; close dependents before shared readers and reap children
before deleting their database/files.

## Results and handoff

The final premeasurement protocols reserve two owner control connections beside
eight runtime PostgreSQL connections (ten combined), require actual queue-age and
parent-monotonic restart observations, and expect existing gateway overload code
429. Sixteen directly owned workload commands cover the two profiles, actual
backup/drop/restore and cleanup. The fixed study seed is 39; synthetic auth
identity nonces remain private.

The image gate uses five source children or nine isolated-consumer children plus
seventeen directly owned offline package commands, for twenty-six total installed
children. Both retain the reviewed thirty-two-child/two-MiB capture ceiling. Group
ownership is registered before fallible observations; actual process-group absence
and direct-child reaping are prerequisites for dependent deletion. Startup, false
close, timeout, descendant and expired-final-budget faults are covered. The parent
holds the original parsed fixture oracle before execution and validates auxiliary
image enrollment before starting the public consumer. Five client canonical HTTP
request/result pairs are directly observed; server result digests are correlated
from those pairs, rather than a second independent observation of response bodies.


Current measured gates passed within selected scope:

| Gate | Observed result | Ownership and limits |
| --- | --- | --- |
| P2 bounded workload | 24 assertions, 81.819 seconds, 16 owned commands | Seed39; 64 capacity inputs plus 1,002 dormant-profile inputs, 68 distinct logical operation acceptances; one actual two-waiter SQL graph; zero per-case rooms/agents and complete cleanup |
| P3 image source | 20 assertions, 7.444 seconds, five owned commands | Eight settled scripted provider entries, seventeen actual worker exits and five canonical public HTTP results; complete cleanup |
| P3 installed image | 20 assertions plus eight maintained offline package assertions, 65.835 seconds | Fresh isolated Python/npm consumers; 26 owned commands including seventeen directly owned package commands; complete cleanup |

The image source assembly review revalidated all five proof files, source-before/
after/current equality and literal field/region joins. Installed-image independent
review, P2's fresh seven-stage npm consumer and 187 compatibility assertions, and
P3's 146 selected policy/recovery/registered compatibility assertions passed.
Shared quality, ordinary readiness/smoke and final preservation/physical assembly
checks passed within the selected local scope. These passes do not close
all full charter rows or authorize durable P1 image execution.

Three failed P2 attempts remain immutable. The first exposed fixture default inbox
logging against the fixed capture budget; the second exposed gateway logging.
Fixture observers are now explicit, while the declared held-observer case and
product defaults stay intact. Restore uses quiet success output with error-stop,
single transaction and independent full-data comparison preserved. The third
reached verification after both profiles and failed an unsupported table-count
assumption. Both snapshot readers now require the exact twenty-nine table names
independently derived from frozen v7 owner DDL. The successful fourth attempt
repeated all stages and populated backup/drop/restore from fresh state; earlier
intermediate observations were not reused to qualify it. No workload threshold,
resource/capture budget or case inventory was widened.

The first image attempt failed safely because the compatibility corpus is larger
than the fixture's default setup-file reader. Only the exact whole legacy corpus
now permits 64 KiB; runtime requests, other setup files and proofs retain their
original limits. Regression coverage also verifies atomic PID marker publication,
strict release identity and bounded waiting through the exact owned hard-link
publication transition. Python proof files already published complete bytes; its
peer reader now handles that exact transition. The independent oracle, packaged
README bytes, product runtime and canonical policy wire bytes were preserved.

All failed attempts, reviewed protocol/source successors and diagnostic corrections
are retained. Scripted fixture extraction remains separate from general OCR/model
inference, deployment capacity and complete charter/release qualification.


### Measured local observations

| Observation | Actual value | Interpretation |
| --- | --- | --- |
| Sampled Node RSS peak | 236,693,808 bytes | One configured process per sampled profile; no per-case or deployment-wide inference |
| Sampled event-loop maximum | 28.869 ms | Declared local workload; below the fixed 1,000 ms study ceiling |
| Admission maxima | Steady n = 16: 44.684 ms; burst n = 3: 61.953 ms; slow n = 4: 20.533 ms; fill n = 40: 43.455 ms | Small cohorts have no p95; fill nearest-rank p95: 33.149 ms; original 5-second ceiling preserved |
| Useful completion | n = 63 maximum 2,578.128 ms; p95 2,141.237 ms | Separate from admission and human acknowledgement; original 15-second ceiling preserved |
| Observed process restart | 975.490 ms | Parent monotonic serve exit through fresh stage completion; includes startup and verification |
| Durable pending queues | Capacity 0/age null; dormant 998/oldest 66,843.293 ms | Database-clock observations; no detached timing subtraction |
| Restored durable identity | 1,066 original inputs and 68 logical operations | Both profiles’ exact 29-table before/restored snapshots, raw dump, fresh reopen and equal replay joined; zero extra logical acceptances |

Final shared gates passed 2,272 Python tests, 1,318 TypeScript tests (503 console,
660 P2, 155 specialist), broad/strict Python typing over 146/140 sources,
403-file Python formatting and documentation validation for all 115 maintained
documents. All 29 Mermaid bodies passed syntax-only parsing. Source-bound artifact
and independent reviews preserve failed attempts and clarify authored components.

P1's 77 runtime payloads, all 50 default service files, default UI, dependencies,
locks, image pins and original M1 remain preserved. The closed prior checkpoint's
1,535 artifact hashes were reverified and all 734 prior public paths remain present.
P3 intentionally grows to 32 Python runtime payloads and 27 npm payloads; current
fresh archives/public exports were qualified, with old policy wire behavior intact.
Full catalog status remains 55 defined/24 registered, with all 17 P2 and remaining 14
P3 rows planned. No paid providers, remote CI or publication were required.

Next are P2-I20's joined operations/telemetry UI and P3-I17's fixed-policy evidence
extension. Durable image composition still requires a reviewed versioned P1
operation extension; native revision0 continuation requires a coherent versioned
cross-language command change before full integrated release. Those prerequisites
remain explicit and do not become authority from displayed context or extracted text.


### Harness reliability and compatibility closure

The final fresh P2 compatibility batch passed all 187 assertions in 139.105 seconds;
its eleven lanes bound 317 actual source/runtime/build inputs before and after
each execution. A separate affected 119-assertion batch passed first and was not
reused to complete the fresh 187. Installed npm passed seven stages; the current
isolated Python consumer passed 113 unadapted tests in fifteen commands. P3 passed
all 146 policy/recovery/installed/registered assertions across ten fresh lanes.
The maintained sixteen-assertion policy gate is included in those 146; the image
installed gate separately ran its eight-assertion offline builder.

Earlier compatibility attempts remain failed. Playback exposed an unsafe marker
publication window and insufficient failure-work retention; its lost original
inner cause remains unknown. A controlled source counterexample reproduced the
marker race, atomic publication was added, and the wrapper now retains bounded
payload-safe diagnostics and unresolved owned work. Dependent database/room/file
cleanup is withheld until actual child ownership settles. Later read-only zero
residual observations and separate marker-only recovery do not rewrite earlier
cleanup:false reports.

Rehydration and send-policy fixtures exposed unbounded entry waits and deferred
rejection observation. The systematic fixture audit added immediate outcome
observation, finite entry/caller/watchdog races and final settlement joins, with
eight maintained Vitest regressions. The original 25/30 ms timeout calls and exact
error codes remain covered; a legitimate early timeout need not have entered an
external port. Separate normal-budget calls abort only after actual held-port
entry, proving retained ownership, overload/incomplete-close behavior and later
useful progress without relying on cold SQL finishing within 25/30 ms.

Independent owner checks bind every recovery command to its original scope,
case, conversation, attempt and operation. The cap remains 128 commands. Missing
observations must equal the exact two deliberately killed command identities,
plus only an individually joined admitted deadline command when its observation
is absent. Known-only original-ID replay is explicitly executed in fresh and
populated restored processes with zero new provider/lookup/retry invocations.
The focused run observed an admitted-and-observed deadline command; the selected
full run observed no admitted deadline command and therefore made no call for
that absent identity. The admitted-without-observation alternative is covered by
pure validator tests and is not claimed as an additional measured branch.

The source-closure audit strengthened the final P2 guard from its predecessor’s
narrower inventory to all executed fixtures and direct build/media inputs. A stale
descriptive lane checksum in preserved plans is distinguished from the matching
authoritative source maps and actual per-lane checksums. P3’s first compatibility
supervisor attempt failed while publishing to the shared temporary parent; its
private output sink was corrected without changing inner gates. The final 146
batch was fresh. All failed reports, exact input/protocol successors and safe
raw captures remain immutable in the private indexed phase evidence.
