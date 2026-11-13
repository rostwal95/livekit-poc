# Harness architecture

Status: Active
Last reviewed: 11 November 2026

The development harness makes module ownership, architecture rules and acceptance
evidence executable. Structural and behavioral lanes have separate outcomes.

## Components

| Component | Responsibility |
| --- | --- |
| harness/foundation.json | Mandatory non-product runtime ownership, entrypoints, docs and import constraints |
| harness/modules | Ownership, source state, required docs, boundaries and test mapping |
| harness/rules/static.json | Shared structural groups and scanning conventions |
| harness/documentation.json | Ecosystem corpus and documentation quality rules |
| harness/static_check.py | Metadata validation, affected-module selection, boundary checks and current suites |
| harness/documentation_check.py | Structure, metadata, link and reference-form checks |
| harness/catalog.json | Acceptance discovery and implemented runner registration |
| scripts/harness-check.sh | Fast structural and implemented-test entry point |
| scripts/harness-deep.sh | Behavioral acceptance entry point |

## Outcome semantics

The structural groups are docs, contract and boundary. A separate foundation
contract protects the existing services, app, setup and shared fixtures even when
a product selection is focused. It adds no fourth product or acceptance prefix. A passing result certifies
only those checks and executed suites. Product acceptance is separate. Missing
product implementations remain incomplete.

Behavioral scenarios use stable IDs, explicit prerequisites, bounded execution
and diagnostic artifacts. Negative fixtures demonstrate that each new rule
catches its intended violation. Positive fixtures establish that valid behavior
remains usable.

The engine executes registered unittest suites and closed python_json_report
commands. Report execution binds the exact case and catalog mode, owns bounded
child capture/cleanup and exposes only validated fixed codes/counts; product
wrappers own prerequisite checks and exact test-ID mappings. Future TypeScript,
browser and container runners must retain failures, missing tests,
required skips and timeouts as non-passing results. Runtime tests establish
recovery, cancellation and media behavior; static scans cannot establish them.

Selected linked-confirmation/result-projection gates own explicit setup, exact
assertion inventories, fresh source-bound reports and actual process/schema/socket
cleanup. They do not register new complete acceptance rows. Offline test discovery
includes the additive P1 feed and local confirmation bridge; the explicit database
lane adds owner v4 adoption/crash and atomic result-cursor tests while preserving
all older P1 regressions. P3 stores derived observations/checkpoints, never an
execution queue. Its work item records passing selected local qualification.

The qualified selected outbound-reply/processing gates retain exact named inventories and
role-separated private setup. Owned PID barriers must precede process-loss claims;
finite child capture, first-failure preservation and independent cleanup remain
mandatory. Processing source history, projection checkpoint, scan progress and
terminal ACK watermark are separate observations. No gate can replace unknown
provider acceptance with a failed-for-retry status. New gates register no complete
charter row until all normative assertions exist. The completed phase retains
24 P2 and 16 P3 named assertions, isolated installed consumers and fresh prior
regressions. Their exact reports preserve uncertainty and owned cleanup.

The [completed send-policy/action-race phase](work-items/0035-send-policy-and-action-races.md)
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

## Selection and evidence

Focused checks select modules or structural groups. Shared policy/configuration
changes expand to all modules. Unknown ownership or unavailable comparison
baselines fall back to full scope. Current fast tests cover all implemented Python
suites even when structural inspection is focused.

Reports live under ignored .local/harness and retain status, original process
outcome, test counts, elapsed duration and diagnostic paths. Future runtime reports
add fixture/workload, code snapshot, stack and media evidence as specified in the
[validation plan](validation-plan.md).

## Maintenance

Update contracts, mappings, docs and fixtures with implementation. Keep CLI usage
in the [harness guide](../harness/README.md), runner design in
[harness/Design.md](../harness/Design.md), and behavior in project charters.

## Native and deadline selectors

Use make p2-native-build to build the P2 SDK then isolated optional page, and make
p2-native-check
for the explicitly owned native qualification attempt. The selected browser
inventory has six groups; SDK/storage/expiry checks are separate assertions,
not fabricated extra browser cases. Selected actual native and isolated Python/npm
artifact gates passed; final selected phase checks and the affected media rerun passed. The native gate owns its temporary room/schema/roles/host children
against the local Docker SFU/PostgreSQL; it does not alter default M1/P1 deployment.
Keep raw private RTC/configuration artifacts transient and retain only reviewed
safe evidence. Missing media, required assertions or cleanup cannot pass.

make p3-deadlines-check passed eighteen selected source assertions and the same
isolated installed assertions; forty-six old execution/applicability/action-race
assertions also passed. Its bounded intentionally noncooperating peer is test-only;
production runtime and P1 authority are unchanged. Keep role-separated commands,
actual clock-after-admission lock evidence, one verified postcommit kill, strict
three-proof identity joins and finite cleanup/capture budgets. Diagnostics cannot
qualify. See the [completed handoff](work-items/0036-native-input-and-deadline-cancellation.md). Catalog registrations remain 24 of 55;
seventeen P2 and fourteen P3 complete rows remain planned.
