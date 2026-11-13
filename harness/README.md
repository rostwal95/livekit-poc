# Ecosystem development harness

Status: Active
Last reviewed: 13 November 2026

## Overview

Discover requirements, check repository contracts and execute implemented tests
through a bounded local interface. Structural validation and product acceptance
have separate outcomes.

## Root fast-suite execution

The root tests directory uses two fixed owned Python processes under one aggregate
120-second deadline, including five seconds reserved for cleanup. Both discover
the entire canonical suite independently and must publish identical ordered test
IDs before execution is admitted. Three measured SDK-heavy modules form one
partition; the other process executes the exact complement. Actual started IDs,
counts, exit codes and zero required skips must match both manifests.

Project and registered acceptance lanes retain their existing runners. Root stdout
and stderr are private and bounded to one MiB per stream/two MiB aggregate;
validated timeout progress contains no raw exception text. The retained manifest,
result, capture and actual owner records make the selection inspectable. Ordinary
successful fixture cleanup does not establish universal descendant containment.
Forced stop leaves nested cleanup explicitly unverified and cannot pass.

## Implementation status

The foundation includes mandatory infrastructure ownership/entrypoint checks,
product module contracts, documentation quality checks, known import boundaries,
negative fixtures, acceptance discovery and unittest execution. BASE-01 runs M1
intake; P1-01/P1-02/P1-03 run the shared five-test accepting-process suite, and
P1-04/P1-05 run the shared four-test independent supplier/worker suite.
The catalog owns current complete runner registrations; full product coverage
remains pending. Separate root frontend commands and the local setup smoke verify
the implemented console and transport foundation. These checks are not registered
as completion of the planned product scenarios. The dependency-free H1 workload
model validates frozen seeded declarations; its explicit local-setup consumer
measures installed inquiry services in a separate lane. No benchmark runner is
registered as a complete charter row. All twenty P1 charter rows now have
registered runners: SQLite process suites, exact PostgreSQL assertion mappings
and fresh infrastructure reports. Retained P1-01 through P1-20 reports passed.
P1 V1 is qualified for the local POC using provider_real v2; local_real remains
unqualified. P3-01/P3-03/P3-11 now have complete registered lab runners and fresh
passing reports. The catalog has 24 registrations of 55 cases: BASE-01, 20 P1 and 3 P3.
All 17 P2 and remaining 14 P3 rows stay planned, so full aggregates remain incomplete.

The [completed linked-confirmation/projection phase](../docs/work-items/0032-linked-confirmation-and-result-projections.md)
adds selected P2/P3 gates and work-profile v4 tests; selected local phase
qualification passed. Catalog registrations remain 24 of 55. Full Python
validation includes the new public feed/bridge boundaries; the explicit PostgreSQL
lane includes feed migration/crash/cursor tests and existing regressions. No test
count, structural result or selected phase gate registers a full product row.

The [completed outbound-reply/processing phase](../docs/work-items/0033-outbound-replies-and-completion-processing.md)
completed its selected local P2/P3 gates, including 24/16 named assertions and
isolated installed consumers. P2 owns communication attempts;
P3 owns only processing metadata over existing public P1 identities. Exact
role-separated child protocols, real process barriers, finite captures and owned
cleanup passed. That phase recorded 1,501 Python/723 TypeScript
tests, broad 133/strict 95 typing sources and 321 formatted Python files. The catalog remains
24 registrations of 55; no complete new row is implied.

The [completed send-policy/action-race phase](../docs/work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Preserve the
completed callback/applicability checkpoint. P2 requires 30 named actual assertions,
including populated inbox v4-to-v5 migration/restore, ordinary unknown holds,
cooperating same-key retries, callback ordering and independent provider ledgers.
P3 freezes 16 cases/31 one-time modes, three owned PID kills and two actual
two-waiter SQL order graphs. Its bounds are 180 seconds total/15 cleanup, at most
32 children, 128 KiB aggregate capture, 2 KiB per stream and a 32 KiB final report.
Prewarm both writers and the same owner locker/observer before lock contention;
never change P1's lock timeout. Validate exact keys and JSON primitive types,
first-failure precedence, role-separated environments and complete cleanup.
Optional diagnostic runs retain only bounded redacted failure streams and always
remain non-qualifying. Actual, isolated installed and prior regression gates passed for this slice;
require them after affected changes. No complete charter registration or P1/P3 runtime change is
introduced; physical delivery/human ACK remains distinct from provider evidence.

### Current native/deadline selectors

The [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md)
adds explicit optional gates. P2 passed the selected actual six-group native and
isolated Python/npm package gates; focused checks passed fifty-five Python, 530 P2
TypeScript, sixty-five browser-policy and forty-five wrapper tests plus one local
HTTP proxy regression. Final selected phase regression/shared checks and the affected media
rerun passed. P3's selected eighteen source and eighteen installed temporal
assertions and forty-six compatibility assertions passed through unchanged P1/P3
production authority. Full product rows and registrations remain unchanged; see
the shared validation guide for exact evidence.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md),
[harness architecture](../docs/harness-architecture.md),
[validation plan](../docs/validation-plan.md) and
[documentation standards](../docs/documentation-standards.md).

## Requirements

Run from the checkout root using the frozen environment installed by make
bootstrap. The harness engine uses the standard library, but the full fast lane
also discovers service tests that require all declared extras. Offline
checks require no credentials or remote services. Use HARNESS_PYTHON to select
the same interpreter as the project environment.

## Commands

```sh
.venv/bin/python -m harness validate
.venv/bin/python -m harness list
.venv/bin/python -m harness list --project p1
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1 --groups boundary,contract
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --changed --base HEAD
```

The fast lane checks selected structural groups and all implemented Python suites.
Groups are docs, boundary and contract. The docs group validates the shared
corpus, including architecture decisions. The mandatory foundation.json policy
checks services, the console, local setup and shared contracts on every selected
product scope. Missing entrypoints/policy and forbidden imports cannot be hidden
by selecting another project. It creates no additional product acceptance cases. Unknown ownership or an unavailable comparison baseline expands affected
scope conservatively. Shared harness, contract or instruction changes require
full checks.

```sh
.venv/bin/python -m harness run BASE-01
.venv/bin/python -m harness run P1-05
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh
```

BASE-01, all P1-01 through P1-20 and P3-01/P3-03/P3-11 have executable registered runners.
P1-05 retains its independent supplier/worker assertions; later PostgreSQL and
infrastructure runners execute their exact mapped requirements. Catalog metadata
is not a fresh result. P1 deep requires actual PostgreSQL, browser/media and the
selected real-inference setup. P1-20 defaults to local_real; use the documented
trusted provider selector explicitly for provider_real. P2/P3 planned rows still
produce incomplete project/ecosystem aggregates with exit 2. Keep missing or
failed evidence non-passing; remote CI is outside the POC scope.

The design-role policy enforces unique ordered sections, populated requirement
tables and section-owned Mermaid type/body presence. Positive/negative fixtures
cover comments, fenced/indented examples, escaped pipes and invalid policy. Actual
Mermaid parsing and semantic design review remain separate from structural checks.

### Complete selected P3 lab cases

With the documented restricted-role local PostgreSQL and pinned Node setup:

```sh
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

These execute fresh 13/8/12-assertion components through p3_acceptance.py; they do
not reuse a previous passed report. Validate exact named inventory, fixed lab mode,
zero required skips/errors/failures, stdout/file equality and owned cleanup. The
child environment excludes ambient provider/PG/proxy/interpreter selectors; only
explicit component orchestration receives local runtime/owner setup. Raw child
capture is bounded/private/ephemeral. Retain the component path/hash and fresh
outer report. No image decoding, native media, new model qualification or full P3
release is established. See the [current work item](../docs/work-items/0031-revision-routing-and-delegation-acceptance.md).

### Opt-in inquiry workload declaration

From the repository root:

```sh
make p1-benchmark-plan
```

This invokes local-setup/scripts/p1_benchmark.py without --run. It validates the
[versioned manifest](workloads/p1-inquiry-v1.json), prints its canonical digest and
six experiment names, and returns status not_started. It starts no workload.
The standard-library [workload model](workload_models.py) rejects duplicate/unknown
fields, unsafe input, nonfinite/unbounded values and inconsistent schedules/caps.
Freeze the reviewed manifest/digest before measurement; its six modes declare
168 new offers, 120 admissions and 48 capacity rejections, not actual outcomes.

make p1-benchmark explicitly executes the installed HTTP/worker lane after the
[local prerequisites](../local-setup/README.md). The runner belongs to local setup;
there is no new harness run ID or catalog registration for this partial workload.
A pass needs actual useful results, independent supplier reconciliation and owned
cleanup. The [H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md)
owns the completed local inquiry measurement and inspected evidence. Full H/P1
release and broader workload qualification remain separate.

### Other explicit local phase H gates

From the repository root, make p1-reliability-plan validates the frozen reliability
declaration without executing it; make p1-reliability runs its owned local fault
workloads. The [reliability work item](../docs/work-items/0015-p1-reliability-workloads.md)
owns actual results and limits. make p1-package-check builds/rebuilds the standalone
P1 artifacts and runs isolated installed consumers; the
[package work item](../docs/work-items/0016-p1-standalone-package.md) owns its final
local host/container qualification. Neither a plan nor an artifact build alone
completes a workload, media or release assertion. Real models/media use their
separate [operations guide](../docs/local-real-inference.md).

### Fresh registered runtime acceptance

P1-14 and P1-18 execute in lab mode. P1-20 executes in live mode for actual
inference: default local_real uses prepared Whisper/Qwen/Piper, while explicit
provider_real uses Deepgram/OpenAI/ElevenLabs. The latter needs provider keys;
local_real does not. Neither requires hosted LiveKit or a carrier. Every applicable
actual assertion must pass independently of mode labels.

The infrastructure catalog ceiling is 900 seconds; the product wrapper retains an
original 840-second total deadline. The browser helper has 600 seconds of work and
180 seconds for cleanup. Neither an observation timeout nor a retry extends the
original deadline. The ordinary runner ceiling remains 300 seconds.

Every invocation creates new owned evidence. P1-14 combines the six-case scripted
browser lane and three post-commit database assertions, with a fresh combined
pass recorded in the package work item; P1-18 runs the selected
saturation/shutdown workload; P1-20 runs the two-case browser/model lane for its trusted selected real profile.
The wrapper verifies current source/input provenance, actual raw browser runner
results, independent durable truth and cleanup. It cannot adopt a previous G/H
report. Missing setup, required skips, invalid modes, timeouts or incomplete cleanup
remain non-passing. Use the [operations guide](../docs/local-real-inference.md)
for explicit preparation and the relevant work item for inspected actual results.

For external provider inference use the explicit trusted selector:

```sh
P1_ACCEPTANCE_REAL_PROFILE=provider_real .venv/bin/python -m harness run P1-20
```

The default remains local_real. Both report live and retain the same original
work/cleanup deadlines, two actual browser cases and authority assertions. The
provider lane requires real SDK usage and exact sanitized model/provider spans,
while it observes only native/API/worker resources; external provider CPU/memory
are unknown. See the [provider operations guide](../docs/provider-demo.md).
Neither mode has passing real-media qualification until its own fresh evidence passes.

### Optional native/deadline checks

Run from the repository root after frozen dependency setup and the documented
local stack/restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

The first command builds the P2 SDK, then the isolated p2-native.html entry to
dist-native. It starts no service and changes no default console entry. The second
owns the selected qualified host SDK/browser/gateway exercise against local Docker
LiveKit/PostgreSQL; the third is the qualified selected P3 temporal gate. Final
phase gates and the affected media rerun after the UI hint update passed.
Scripts use ordinary local setup, never provider credentials.
The [completed handoff](../docs/work-items/0036-native-input-and-deadline-cancellation.md) owns exact evidence and prerequisites.

### Result receiver qualification

From the repository root, `make p2-result-receiver-plan` prints the finite
sixteen-storage/four-return schedule. `make p2-result-receiver-check` uses isolated
owner/runtime PostgreSQL profiles, one scheduled receiver-caller kill and actual
backup/restore; it creates no room, provider call or carrier send.
`make p2-result-receiver-package-plan` and `make p2-result-receiver-package-check`
run the separate offline archive/installed lane: twenty-five owned groups, eight
existing package assertions and twenty copied fake-port tests. That lane claims
zero actual storage/return assertions. The [work item](../docs/work-items/0043-stable-result-delivery-and-return-context.md)
records prerequisites, exact outcomes, retained failures and full-phase status.


### Original channel-input qualification

From the repository root, with the existing local PostgreSQL/API and pinned host
Python/Node toolchain:

```sh
make channel-origin-plan
make channel-origin-unit
make channel-origin-check
```

The selected source gate passed fourteen actual assertions across sixteen owned
process groups, with complete cleanup. It joins native/signed simulated-SMS
input to original P1 work, issued policy results and the current P2 receipt/read.
It uses three disposable schemas and one owned post-commit ACK-host kill; the
normal application and M1 record remain unchanged. Reports use fresh timestamped
paths under .local/validation/p2-channel-origin. Failed runs remain retained.

The separate make channel-origin-package-check validates built/installed public
artifacts with explicit fake ports; it does not repeat the actual database
schedule. See the [origin work item](../docs/work-items/0044-origin-bound-channel-policy.md) for exact scope, failures and evidence.
Integrated browser voice/text/SMS, provider composition, restart discovery and the
final demo video remain separately gated.

## Validation

Metadata validation checks required files, scoped acceptance IDs and runner
registration. Foundation policy validates declared ownership, implemented roots,
nonempty entrypoints and required per-area docs. Unknown/duplicate fields, unsafe
paths and boundary roots outside their declared sources fail closed. Structural success does not certify product behavior. Runners must
observe a positive test count; zero tests, required skips, failures and timeouts
cannot pass. Missing implementations produce not_implemented and group incomplete.
A single runner preserves ordinary nonnegative process failures; signal exits map
to 1, timeouts to 124 and invalid metadata/selection to 2.

Reports under ignored .local/harness contain run/scenario IDs, status, original
runner exit, test/skip counts, duration, command and diagnostic paths. The closed
python_json_report acceptance protocol remains separate from H1 workload artifacts,
which already bind mode, canonical manifest, installed source/image, machine and
bounded raw timing/resource records. Media evidence remains its own lane. See the
validation plan for release requirements.

Frontend verification remains explicit: run pnpm check, pnpm test and pnpm build
from the root, or make frontend-check. Actual local media requires the setup
manager smoke command. Python fast success does not imply those lanes ran.
Local quality gates include the existing Ruff format check.

Register implemented cases in catalog.json only after their actual assertions
exist. Three runner kinds use safe relative paths, argv arrays and explicit deadlines:

| Kind | Mode contract | Maximum catalog deadline |
| --- | --- | --- |
| unittest_discovery | Registered baseline/offline suite metadata | 300 seconds |
| python_json_report | Exact catalog offline/lab/live mode | 300 seconds |
| python_infrastructure_report | Exact catalog lab/live mode; offline rejected | 900 seconds |

Both report kinds use owned 64 KiB bounded capture and a closed numeric report
bound to the exact case and mode. Raw output/unvalidated reports stay private and
are removed; retained diagnostics contain fixed safe codes/counts. Product wrappers
own prerequisites and exact assertion mappings, not the generic engine. Extend runner kinds deliberately with positive and
negative fixtures. Do not register placeholder commands as completed behavior.

### Phase E evidence

The offline lane discovers mutation DTO, supplier, sink and authenticated effect
service tests. The explicit PG lane additionally requires v3 upgrade, mutation,
effect/outbox and compatibility boundary files; process crashes are actual owned
children against independent persisted fixtures. make phase-e-demo exercises five
fresh installed runtime containers with two external-commit losses and checked
cleanup. Artifacts remain in .local/validation/p1-phase-e, separate from historical
phase reports. Core effect/cancel/event/receiver dedup records are retained when
diagnostic projections are pruned. A timeout or missing suite never passes.

Phase task completion does not register the complete charter requirement. The
catalog owns current complete registrations; missing required rows remain non-passing.

### Phase F evidence

The offline lane includes lease DTO and actual owned worker process tests. The
PG gate requires v4 upgrade/lease/coordination suites, including independent
workers, stale external calls, lock-time expiry, saturation and useful progress.
make phase-f-demo uses the actual worker profile, preserved synthetic state and
installed source hashes. Required setup, zero tests, skips and timeouts fail.
Private health/metrics snapshots do not replace business outcome/receipt records.
Keep artifacts in .local/validation/p1-phase-f and preserve earlier phase gates.
Current complete runner registrations remain distinct from granular phase completion;
read the catalog instead of inferring coverage from suite totals.

### Workload evidence boundaries

H1 artifacts live under ignored `.local/validation/p1-phase-h/<run-id>`, not the
acceptance catalog's .local/harness reports. The first-result snapshot is validated
from submit/replay/GET and source-labelled. All HTTP operations share declared
concurrency; case observation is one global round-robin GET followed by a 250 ms
sleep, including HTTP/queue lag. Resource probes target one second with actual
start/end/duration and skipped intervals, not guaranteed one-Hz observations.
Sequential in-container Python probe overhead is included. Accounted cgroup memory
is not RSS or a peak; CPU microsecond counters have explicit first/last/delta/window.
The window includes later cancellation/delivery checks. Summary statistics are
count/minimum/median/maximum; no small-sample tail percentile, speech/model metric
or production capacity follows. The
[observability guide](../docs/observability.md) owns detailed interpretation.

Original failures retain fixed-enum operation/code and observed bounded process
exit/timeout/budget/elapsed metadata before temporary capture removal; cleanup
failures remain separate. Raw command/output/environment/body/exception text is
excluded. Automatic host/runtime metadata does not include Docker-VM hardware;
separately collected operator environment evidence must be labelled accordingly.
Missing setup/progress/observations, unknown unresolved acknowledgement, deadline
or failed owned cleanup remains non-passing. A pre-cleanup measurement snapshot
is not a phase pass. Preserve safe failed evidence and closed G artifacts. Do not
convert this H1 contribution into a complete acceptance runner or release claim.

The selected checkpoint passed 1,660 Python tests (49 P1, 14 P2, 238 P3,
1,359 root) and 861 TypeScript tests (326 console, 457 P2, 78 specialists), with
broad 138/strict 108 type sources and 340 files passing Ruff formatting. The
30-case P2 and 16-case P3 source gates, isolated installed consumers and prior
111 P2/101 P3 regression assertions passed. These are correctness checks, not
production capacity or real-media measurements.

## Next milestone

Keep the independent inquiry-worker crash scenarios and explicit PostgreSQL
cutover/parity lane and the G native/media/trace gate passing while H release
qualification follows the [build plan](../docs/build-plan.md). Retain and reproduce
the S-I06/P1-I27 inquiry baseline qualified locally under the
[H1 work item](../docs/work-items/0014-p1-phase-h-workload-baseline.md).
H2 restart/slow-dependency/saturation/shutdown measurements and P1-I26 host/Linux
isolated artifacts, independent API/failure review and genuine native consumer
passed. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified. Keep BASE-01 and selected P3-01/P3-03/P3-11
lab assertions passing, preserve historical source-bound evidence, and retain
planned status for all 17 P2/remaining 14 P3 rows and unqualified local_real status.

The real database gate is make postgres-check after the documented local role
setup. Tests under tests/postgres use explicit pg_*_cases.py discovery and require
actual PostgreSQL credentials; they are not silently skipped by the fast lane.
The lane records its own report under .local/validation/postgres (or the explicit POSTGRES_REPORT path). Its evidence
contributes to backend/migration/scope requirements. F/G additionally contribute
lease, worker and local speech-interruption evidence. Exact complete assertion
mappings, rather than granular phase counts, govern the twenty current P1
registrations. No single phase establishes whole-project release.

## Conversation/browser gate

make phase-g-demo runs the installed native business profile through the real local
browser/media, current projection, exact UI approval and inspected raw Jaeger v3
trace path. Its [work item](../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
records the inspected local combined gate. Explicit bundled-WAV WebAudio input
and native scripted providers establish transport/lifecycle, not physical
microphone or configured inference quality. The public RoomIO barrier and native
ready attribute gate controls; alternate SDK session hosting is disabled.
Offline native/manual-audio and trace-wire tests remain separate from this lane.
The runner must fail missing browser/dependency/fault setup rather than skip it.
Artifacts live under .local/validation/p1-phase-g and keep credentials out of
browser recordings and diagnostics. Granular phase success alone does not pass
a registered charter row or whole-project release. Hardware
capture, automatic network-loss recovery and actual local-real engine/media evidence
remain separate. Remote CI/publication are outside the local POC scope.

## Playback and process recovery validation

Selected I17/I14 gate commands and exact outcomes are recorded in the
[current handoff](../docs/work-items/0037-playback-evidence-and-process-recovery.md).
make p2-communication-check runs sixteen direct public-API/PG groups; make
p2-playback-check runs three actual SDK/browser groups in one Playwright case;
make p3-recovery-check runs seventeen actual process-recovery assertions.
Default M1/P1 startup and the 55-case/24-registered catalog remain unchanged.

The wrappers require exact closed reports, retained hashes, actual process/backend
ownership, normal and negative/useful-progress paths, and complete cleanup.
Safe diagnostics cannot qualify a failed normal run. Current installed npm/Python
consumers are measured separately. No complete P2/P3 charter row becomes passing
from a task label or mocked media fact; missing full rows remain non-passing.

## Workload and document commands

The [completed handoff](../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records passing selected P2-I19/P3-I16 qualification. From the frozen repository environment,
make p2-workload-plan and make p3-document-plan expose their fixed inventories
without starting work. make p2-workload-check selects twenty-four local synthetic
PostgreSQL/HTTP/workload assertions. make p3-document-check selects eight contract
and twelve actual image socket/lifecycle assertions; make p3-document-package-check
repeats those twenty from fresh isolated artifacts after the maintained offline-eight
package builder. None is a new catalog acceptance runner.

Preserve each declared aggregate budget across all direct/nested children and
captures; workers are threads, not hidden process counts. Register every child
before fallible post-spawn observation, retain descendant groups and wait for actual
settlement before dependent deletion. Bind the private exact physical-file index,
source/archive inputs, independent literal oracle and all nested summaries. Failure
contexts are finite and first-error preserving; a diagnostic or missing/skipped/
timed-out/incompletely cleaned run never passes. Selected P2-I20/P3-I17 qualification passed;
full seventeen-row P2/fourteen-row P3 acceptance remains planned.

## Operations and fixed-policy commands

The [operations and policy handoff](../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
owns P2-I20/P3-I17. Inspect make p2-operations-plan and make p3-fixed-policy-plan
before the explicit local gates. make p2-operations-check exercises sixteen real
PostgreSQL/HTTP groups and three browser groups in one browser case.
make p3-fixed-policy-check runs eight contract and twelve actual HTTP assertions;
make p3-fixed-policy-package-check repeats the twenty from fresh isolated public
artifacts after a separately counted offline-eight package builder. Plans start no
work and do not constitute qualification.

Keep exact role environments, command/capture/proof budgets, actual owner barriers,
independent factual/durable joins and private physical-file inventories. The
operations UI is a read client, and fixed-policy v2 is standalone HTTP. Preserve
all 55 catalog definitions and 24 complete registrations. Selected slice results
cannot register a full P2/P3 row or grant execution/consent authority.

Selected 0040 gates passed. The operations report binds all eight complete owner
snapshot files through a small canonical manifest and includes each file in its
exact direct proof/index inventory. The original per-file, aggregate, capture,
child and deadline budgets remain unchanged. Preserve all predecessor failures;
a later explicitly approved resource recovery does not rewrite an earlier false
cleanup observation. Current complete registrations remain 24 of 55. Full P2/P3
and integrated video release checks remain separate.
