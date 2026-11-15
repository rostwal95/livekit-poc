# Architecture audit reconciliation and plan updates

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record how a supplied architecture audit was reconciled with current evidence, plans and build targets |
| Audience | Reviewers of architecture findings; engineers planning P2, P3 or operational work; coding agents |
| Scope | Finding disposition plus immediate plan and build-target corrections; excludes runtime, schema and provider changes |
| Owns | Audit finding disposition, observed verification and handoff |
| Related | [Root design](../../Design.md) · [P2 charter](../projects/channel-continuity-scope.md) · [P3 charter](../projects/delegation-reliability-scope.md) · [Operational extensions](0021-p1-operational-safety-extensions.md) · [Release work item](0019-p1-phase-h-release-qualification.md) |

## Behavior and scope

This work item reviews the supplied architecture and engineering audit against
the current source, project charters, task plans and retained Phase H evidence.
The supplied review explicitly covered an earlier ten-file snapshot, not a full
repository execution. Its unverified findings are hypotheses to inspect, not proof
that a feature is absent.

The review retains the three-project strategy, one durable execution owner and
native LiveKit media. It adds no new project, infrastructure layer, provider
fallback, dependency upgrade, remote continuous integration (CI) or publication.

| Review criterion | Safety | Useful progress and evidence |
| --- | --- | --- |
| Current versus old claims | Preserve completed source-bound evidence and explicit limits | Map every material recommendation to current evidence, correction or planned owner |
| Contracts and plan | No future capability is labelled implemented or registered as passing | Concrete negative and valid-progress criteria in existing P2/P3 tasks and operational work item |
| Immediate corrections | No runtime/schema/authority change; preserve package artifacts and original keys | Root test target covers both Python suites; diagram expresses planned dependency inversion |
| Validation | Missing/zero/skipped/timed-out checks cannot pass | Execute both suites, full shared checks, formatting, documentation and changed Mermaid parsing |

### Terms

| Term | Meaning |
| --- | --- |
| O1 | Planned restored-database quarantine slice, defined in the operational extension |
| O2 | Planned append-only adjudication slice, defined in the operational extension |
| O3 | Planned conditional core compaction slice, defined in the operational extension |
| A and B | An older and a newer case revision, in the action-race row |
| Phase H1 | The P1 inquiry workload baseline |
| Phase H2 | The restart and slow-supplier workloads |

## Interfaces and ownership

| Document | Owns |
| --- | --- |
| [Root design](../../Design.md) | Architecture |
| [P2 charter](../projects/channel-continuity-scope.md) and [P3 charter](../projects/delegation-reliability-scope.md) | Their stable IDs, which they retain |
| Task plans | Implementation sequencing |
| [Operational extension](0021-p1-operational-safety-extensions.md) | Separate planned work after V1 (the fixed version-1 project scope) |
| [Validation plan](../validation-plan.md) | Integration criteria |
| [Technology policy](../technology-baseline.md) | Future local scanner qualification |

No new passing acceptance registration is created.

### Finding disposition

In the action-race row, the ordering evaluates A, commits B in another
transaction, then attempts A's intent.

| Supplied recommendation | Current assessment | Applied action / owned next test |
| --- | --- | --- |
| Finish P1 Phase G and actual voice | Superseded for scripted media and selected provider-real scope | Preserve Phase G and Phase H evidence; physical microphone quality, human hearing and general recognition quality remain unqualified |
| Establish real inference | Selected provider_real v2 passed; local_real remains unqualified | Preserve explicit profile selection and native-only credentials; no paid rerun for documentation changes |
| Prove software development kit (SDK) packaging | P1 host/Linux isolated artifacts and genuine consumer passed; P2/P3 packages planned | Preserve P1-I26 artifacts; enforce separate wheel/npm-pack consumers as each future package exists |
| Reconcile 49 pending requirements | Older count; now 20 P1 cases have retained passing reports and reviewed index | P2/P3's 34 cases remain planned; the 54-case ecosystem aggregate is incomplete; do not derive product pass from test totals |
| Fix stale status text | Most earlier inconsistencies already corrected; remaining foundation/P1 command wording found | Scope historical foundation text and default local_real command behavior precisely |
| P2/P3 planned | Accurate and intentional at this checkpoint | Deliver existing narrow standalone phases before integration; do not treat documentation as implementation |
| Manual adjudication | Genuinely deferred beyond P1 V1 | Planned O2: verified reviewer, append-only sourced decision, protected race/replay, original outcome unchanged, zero supplier retry |
| Backup rollback with newer supplier state | Existing backups/crash tests do not qualify this separate boundary | Planned O1: new restored target, old-consumer containment, dispatch quarantine, independent inventory and no replay when identity/evidence is missing |
| Retention and capacity reclamation | V1 intentionally retains core receipts indefinitely under finite fail-closed caps; diagnostic pruning is tested | Preserve bounded policy; O3 requires tombstones/horizon/restore/crash tests before claiming sustained reclamation |
| Cancellation semantics and late tools | Typed cancellation observations and interruption-safe work ownership already exist | Preserve actual race/media tests; inspect installed SDK interruption behavior; do not rename API to an illustrative method or infer stopped supplier work |
| P1 depends directly on specialist | Real planned-diagram inconsistency; code does not import P3 | Correct to planned generic handler port plus composition-supplied specialist adapter; do not build an unused runtime |
| Recipient versus mutable route | Needs explicit field-level semantics | P2 keeps recipient/logical send stable, revalidates authorized route, preserves ambiguous send and provider retry identity; delayed callback stays with original attempt |
| Account association and order | Already required, lifecycle detail incomplete | P2 adds one-time expiring challenges, revocation/reassignment version, server acceptance sequence and useful valid progression |
| Carrier controls | Fake carrier required; real carrier optional | Generic rate/suppression/replay fixtures first; a later real adapter needs explicit capability/security/receipt/opt-out policy and separate qualification |
| P3 valid JSON versus true facts | Existing evidence/clarification design needs stronger source binding | Bind exact immutable input/source and bounded references; schema-valid wrong fixture values fail factual evaluation; provenance grants no authority |
| P3 actual action race | Already required by P3-06/P3-I12 | Make A-evaluate/B-commit/A-intent and inverse ordering explicit with real PostgreSQL barriers and useful confirmed B progress |
| Integrated security and resource tests | Existing P1 tests; cross-project runtime still planned | Preserve tenant/callback/result isolation, prompt injection as inert input, revision/authorization at commitment, actual safe exports and bounded bursts |
| Numeric budgets | P1 frozen H1/H2/provider workloads exist, not production capacity | P2/P3 freeze their own hardware/mode/schedule/budgets before measuring; retain raw observations and equivalent baselines |
| Build/test discovery | `make check` already covers package tests; `make test` omitted the member suite | Add member discovery to `make test`; future packages enter workspace/lint/type/test/build in their first source slice |
| Python support/dependency pins | Earlier 3.11–3.14 claim superseded by explicit 3.14-only policy and independent distribution | Preserve frozen baseline; no untested wider interpreter support or automatic upgrades |
| Two-document pnpm scanner compatibility | Real future tool requirement, no current repository scanner/parser defect | Plan inventory completeness positives/negative first-document fixture before any scanner/software bill of materials (SBOM) coverage claim |
| Independent developer experience | Installed/automated consumer evidence exists; human onboarding feedback remains pending | Contributor workflow records fresh setup, API/error interpretation and revision rationale; do not manufacture external human feedback |
| Simplify root AGENTS | Useful maintenance advice, no urgent correctness gap | Preserve critical invariants and existing linked phase guides; defer stylistic restructuring that would create broad policy churn |

### Current evidence and limits

The [Phase H handoff](0019-p1-phase-h-release-qualification.md) records:

- the selected `provider_real` v2 qualification;
- the complete four-case current H2;
- real PostgreSQL;
- current scripted and provider media;
- isolated packages;
- the independently reviewed 20-case index.

Those retained reports were inspected for scope. This review does not rerun or
recertify their runtime behavior. Historical evidence retains its own source and
input bindings, and the index documents provenance limitations.

The previous release recorded 1,100 offline Python tests, 263 real PostgreSQL
tests and 326 frontend tests. Those historical counts are not release thresholds.
Prerecorded audio is not physical capture or hearing. A receiver receipt is not
human acknowledgement. One failed API get span has an unresolved cause in a
bounded 100-trace query, so no global zero-error claim is made. External-provider
resources, invoice costs, zero data retention (ZDR) and production scale remain
unqualified.

## Failure cases and validation

This review changes no application runtime, persisted schema, package payload,
provider configuration or UI behavior. Actual paid inference, PostgreSQL fault
runs and artifact rebuilds are unnecessary for these plan and build-target
changes. Keep the original Phase H artifacts intact. The public package README
remains at its artifact-qualified P1-I26 checkpoint. The project README now points
to the current release handoff rather than changing packaged metadata merely for
chronology.

| Gate | Exact command or assertion | Required result |
| --- | --- | --- |
| Both Python suites | `make test` | Root and member suites actually execute; nonzero counts, zero required skips |
| Shared fast | `make check` | Fail-closed structural/docs/test discovery, all maintained Ruff/type checks and both Python suites |
| Format | `make format-check` | Entire maintained Python formatting scope passes |
| Documentation | `.venv/bin/python -m harness.documentation_check` | Full corpus and links pass after final edits |
| Diagram | Parse all three root Design.md Mermaid blocks with retained local Mermaid tooling; include invalid fixture | Three valid diagrams; malformed fixture rejected; parsing does not prove visual layout |
| Semantic review | Inspect exact plan/charter changes against supplied findings | Planned/implemented distinction, same stable IDs, immutable supplier truth and correct route/send identity |

Future integration and O1, O2 and O3 fault scenarios are criteria only. They
remain unexecuted and unqualified until implementation, actual boundary tests and
review.

## Results and handoff

### Review outcome

The review and immediate corrections are complete. Three independent automated
reviews checked operational safety, P2/P3 contract semantics and
engineering/command accuracy. Their material corrections were applied. This is
automated review evidence, not external human usability feedback.

### Executed checks

| Executed check | Observed result |
| --- | --- |
| Corrected `make test` | 1,079 root tests in 134.980 seconds and 21 member tests in 0.306 seconds; both passed, zero skips |
| Initial `make check` | Structural zero violations and 21 member tests passed; root suite exceeded the unchanged 120-second limit; this attempt remains failed |
| Unchanged `make check` retry | Passed: 1,079 root tests in 96.374 seconds plus 21 member tests in 0.386 seconds; zero skips, structural zero violations and Ruff passed |
| Maintained typing | Passed: 88 service/core source files and 28 strict sources |
| `make format-check` | Passed: 222 Python files already formatted |
| Documentation and diagrams | All 91 documents passed; three root Mermaid diagrams parsed and invalid syntax fixture rejected; no visual rendering claim |
| Stable planned inventory | P2 retains 17 acceptance rows/22 tasks; P3 retains 17 rows/24 tasks; both manifests/plans remain planned |
| Preservation | Selected runtime/Docker/evidence samples still match the qualified release; packaged README remains byte-identical to its retained source distribution (sdist) |

The direct suite and shared retry establish passing correctness under their stated
commands. Log comparison found slower execution in several regions during the
first attempt but did not establish its cause. The failed timeout is retained. The
deadline, test selection and assertions were unchanged. Another documentation
check followed the final status and results prose.

### Evidence and next step

The reviewed local artifacts are under
`.local/validation/architecture-review/79265dc00444453da8661afd70d99257`. They
include both shared attempts, direct tests, formatting, documentation, Mermaid and
the final machine-readable summary. No private provider credentials were read. No
paid inference or runtime/store qualification was rerun for these documentation
and build-target changes. Previous Phase H artifacts remain unchanged.

The next implementation should select O1's restored-database containment and
quarantine contract, or an independent P2 contract slice at its existing frontier.
O1, O2, O3, P2 and P3 remain planned; this review does not complete their future
tests. No implicit bulk operational rewrite or new passing catalog row is added.
