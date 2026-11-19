# Harness architecture

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Summarize the harness components, what a passing result means, how checks are selected and where evidence is kept |
| Audience | Engineers and coding agents who change harness configuration, runners or gates |
| Scope | Harness components, outcome semantics, check selection, reports and selected phase-gate rules; excludes CLI usage and detailed runner design |
| Owns | Harness component summary, outcome meaning, check selection and harness rules for selected phase gates |
| Related | [Harness guide](../harness/README.md) · [Harness design](../harness/Design.md) · [Validation plan](validation-plan.md) · [Documentation standards](documentation-standards.md) |

## Overview

This document describes how the development harness is built: its components,
what a passing result means, how checks are selected and where evidence is kept.
It also records the harness rules for selected phase gates. It is for engineers
and coding agents who change harness configuration, runners or gates.

The development harness makes module ownership, architecture rules and acceptance
evidence executable. Structural and behavioral lanes have separate outcomes.

## Components

| Component | Path | Responsibility | Status |
| --- | --- | --- | --- |
| Foundation policy | `harness/foundation.json` | Mandatory non-product runtime ownership, entrypoints, docs and import constraints | Implemented |
| Module contracts | `harness/modules` | Ownership, source state, required docs, boundaries and test mapping | Implemented |
| Structural rules | `harness/rules/static.json` | Shared structural groups and scanning conventions | Implemented |
| Documentation policy | `harness/documentation.json` | Ecosystem corpus, supported card Status values, role section, table and diagram rules, and prohibited references | Implemented |
| Static checker | `harness/static_check.py` | Metadata validation, affected-module selection, boundary checks and current suites | Implemented |
| Documentation checker | `harness/documentation_check.py` | Title, document card, legacy metadata, role section and table, diagram, fence, link and reference-form checks | Implemented |
| Acceptance catalog | `harness/catalog.json` | Acceptance discovery and implemented runner registration | Implemented |
| Fast lane script | `scripts/harness-check.sh` | Fast structural and implemented-test entry point | Implemented |
| Deep lane script | `scripts/harness-deep.sh` | Behavioral acceptance entry point | Implemented |

The documentation checker requires one six-row Field/Value card (Status, Purpose,
Audience, Scope, Owns and Related) before the first section and rejects `Status:`
and `Last reviewed:` lines. It requires a populated table in each required-table
section for the document's role, and it resolves Markdown links and HTML `src`,
`href`, `poster` and `srcset` targets inside the repository. The
[documentation standards](documentation-standards.md) list every rule.

## Outcome semantics

### Structural groups and the foundation contract

The structural groups are docs, contract and boundary. A separate foundation
contract protects the existing services, application, setup and shared fixtures,
even when a product selection is focused. It adds no fourth product or acceptance
prefix.

A passing result certifies only those checks and the executed suites. Product
acceptance is separate, and missing product implementations remain incomplete.

### Behavioral scenarios and fixtures

- Behavioral scenarios use stable IDs, explicit prerequisites, bounded execution
  and diagnostic artifacts.
- Negative fixtures demonstrate that each new rule catches its intended violation.
- Positive fixtures establish that valid behavior remains usable.

### Runner execution

The engine executes registered unittest suites (unittest_discovery runners) and
closed python_json_report and python_infrastructure_report commands:

| Kind | Mode contract | Maximum catalog deadline |
| --- | --- | --- |
| unittest_discovery | Registered baseline/offline suite metadata | 300 seconds |
| python_json_report | Exact catalog offline/lab/live mode | 300 seconds |
| python_infrastructure_report | Exact catalog lab/live mode; offline rejected | 900 seconds |

- Report execution binds the exact case and catalog mode, owns bounded child
  capture and cleanup, and exposes only validated fixed codes and counts.
- Product wrappers own prerequisite checks and exact test-ID mappings.
- Additional runner kinds must retain failures, missing tests, required skips and
  timeouts as non-passing results.
- Runtime tests establish recovery, cancellation and media behavior. Static scans
  cannot establish them.

## Selection and evidence

### Check selection

| Selection input | Selected scope |
| --- | --- |
| Focused check | The named modules or structural groups |
| Shared policy or configuration change | All modules |
| Unknown ownership or an unavailable comparison baseline | Full scope |
| Current fast tests | All implemented Python suites, even when structural inspection is focused |

### Reports

Reports live under the ignored `.local/harness` directory. They retain status,
original process outcome, test counts, elapsed duration and diagnostic paths.
Runtime reports also retain the fixture, workload, code snapshot, stack or media
evidence required by their owning gate, as specified in the
[validation plan](validation-plan.md). These requirements differ by lane.

## Maintenance

Update contracts, mappings, docs and fixtures with the implementation. Keep each
topic in its owning document:

| Topic | Authoritative owner |
| --- | --- |
| Command-line (CLI) usage | [Harness guide](../harness/README.md) |
| Runner design | [harness/Design.md](../harness/Design.md) |
| Behavior | The [project charters](projects) |

## Selected phase gates

These sections record harness rules for selected phase gates, in delivery order.
None of them registers a complete charter row.

| Gate | Assertion or lane | Evidence | Status |
| --- | --- | --- | --- |
| Linked confirmation and result projections (0032) | Exact assertion inventories, fresh source-bound reports and actual cleanup | [Work item 0032](work-items/0032-linked-confirmation-and-result-projections.md) | Qualified (selected local) |
| Outbound replies and completion processing (0033) | 24 P2 and 16 P3 named assertions and isolated installed consumers | [Work item 0033](work-items/0033-outbound-replies-and-completion-processing.md) | Qualified (selected local) |
| Send policy and action races (0035) | 30 P2 assertions; 16 P3 cases and 31 one-time modes | [Work item 0035](work-items/0035-send-policy-and-action-races.md) | Qualified (selected local) |
| Native and deadline selectors (0036) | Six browser groups; 18 source and 18 installed P3 assertions | [Work item 0036](work-items/0036-native-input-and-deadline-cancellation.md) | Qualified (selected) |

### Linked confirmation and result projections (0032)

Selected linked-confirmation and result-projection gates own explicit setup, exact
assertion inventories, fresh source-bound reports, and actual process, schema and
socket cleanup. They do not register new complete acceptance rows.

- Offline test discovery includes the additive P1 feed and the local confirmation
  bridge.
- The explicit database lane adds owner v4 adoption and crash tests and atomic
  result-cursor tests, while preserving all older P1 regressions.
- P3 stores derived observations and checkpoints, never an execution queue.

Its [work item](work-items/0032-linked-confirmation-and-result-projections.md)
records passing selected local qualification.

### Outbound replies and completion processing (0033)

The qualified selected outbound-reply and processing gates retain exact named
inventories and role-separated private setup.

- Owned process-ID (PID) barriers must precede process-loss claims.
- Finite child capture, first-failure preservation and independent cleanup remain
  mandatory.
- Processing source history, the projection checkpoint, scan progress and the
  terminal acknowledgement (ACK) watermark are separate observations.
- No gate can replace unknown provider acceptance with a failed-for-retry status.
- New gates register no complete charter row until all normative assertions
  exist.

The [completed phase](work-items/0033-outbound-replies-and-completion-processing.md)
retains 24 P2 and 16 P3 named assertions, isolated installed consumers and fresh
prior regressions. Their exact reports preserve uncertainty and owned cleanup.

### Send policy and action races (0035)

The [completed send-policy and action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Preserve the completed
callback and applicability checkpoint.

P2 requires 30 named actual assertions, including populated inbox v4-to-v5
migration and restore, ordinary unknown holds, cooperating same-key retries,
callback ordering and independent provider ledgers.

P3 freezes 16 cases and 31 one-time modes, three owned PID kills and two actual
two-waiter SQL order graphs. Its bounds are:

| Limit | Value |
| --- | --- |
| Total time | 180 seconds, including 15 seconds of cleanup |
| Children | At most 32 |
| Aggregate capture | 128 KiB |
| Each stream | 2 KiB |
| Final report | 32 KiB |

- Prewarm both writers and the same owner locker and observer before lock
  contention. Never change P1's lock timeout.
- Validate exact keys and JSON primitive types, first-failure precedence,
  role-separated environments and complete cleanup.
- Optional diagnostic runs retain only bounded redacted failure streams and always
  remain non-qualifying.

Actual, isolated installed and prior regression gates passed for this slice.
Require them after affected changes. No complete charter registration or P1/P3
runtime change is introduced. Physical delivery and human acknowledgement remain
distinct from provider evidence.

### Native and deadline selectors (0036)

#### P2 native gate

| Task | Command | Notes |
| --- | --- | --- |
| Build the native page | `make p2-native-build` | Builds the P2 SDK, then the isolated optional page |
| Run the native gate | `make p2-native-check` | Runs the explicitly owned native qualification attempt |

The selected browser inventory has six groups. SDK, storage and expiry checks are
separate assertions, not fabricated extra browser cases. Selected actual native
and isolated Python/npm artifact gates passed. The final selected phase checks and
the affected media rerun also passed.

The native gate owns its temporary room, schema, roles and host children against
the local Docker selective forwarding unit (SFU) and PostgreSQL. It does not alter
the default M1/P1 deployment. Keep raw private real-time communication (RTC) and
configuration artifacts transient, and retain only reviewed safe evidence.
Missing media, missing required assertions or incomplete cleanup cannot pass.

#### P3 deadline gate

`make p3-deadlines-check` passed eighteen selected source assertions and the same
isolated installed assertions. Forty-six old execution, applicability and
action-race assertions also passed.

- Its bounded, intentionally noncooperating peer is test-only. Production runtime
  and P1 authority are unchanged.
- Keep role-separated commands, actual clock-after-admission lock evidence, one
  verified postcommit kill, strict three-proof identity joins, and finite cleanup
  and capture budgets.
- Diagnostics cannot qualify.

See the [completed handoff](work-items/0036-native-input-and-deadline-cancellation.md).
Catalog registrations remain 24 of 55. Seventeen P2 and fourteen P3 complete rows
remain planned.
