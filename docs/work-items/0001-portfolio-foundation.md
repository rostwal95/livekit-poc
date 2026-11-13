# Portfolio scope and harness foundation

Status: Completed
Last reviewed: 9 November 2026

The requested change fixes the three V1 project scopes, local execution modes,
latest-compatible stack policy and AI coding agent workflow. It adds documentation
and a harness bootstrap; it does not implement the worker, channel SDK or
delegation runtime.

## Change boundaries

- Preserve the existing M1 intake code and investigation-only permission model.
- Define P1-01 through P1-20, P2-01 through P2-17 and P3-01 through P3-17 as
  pending product acceptance requirements.
- Add root and project AGENTS.md, Design.md and README.md files with ownership,
  design boundaries and exact implemented commands.
- Add an acceptance catalog/runner and module/rule checks,
  fast/deep entry points and negative harness tests.
- Record exact upstream stable candidate versions and require clean resolution,
  native import and actual-room checks before stack validation.

## Verification plan

Run current intake and harness tests, validate metadata and all documentation
links, run the fast lane, inspect a baseline execution report, and deliberately
run a pending project gate. The pending gate must return incomplete/nonzero.
Verify focused and conservative changed-file selection. Keep unrelated resume,
interview-guide and artifact files untouched.

## Evidence before changes

The existing 10 intake tests passed on Python 3.14.10. P1 M1 is the only product
implementation.

## Handoff

The full fast lane passed 35 tests: 10 intake tests, 11 acceptance-runner tests
and 14 structural-checker tests. Harness metadata validated 55 cases: the
registered M1 baseline and 54 planned product requirements. Focused P2 checks
selected only P2; a changed-file run without a usable Git baseline conservatively
selected all three modules. The deep lane returned incomplete with exit 2,
reporting one passing baseline and 54 not_implemented cases. This expected result
confirms that product scope is not being presented as completed behavior.

All local links and code fences in the 25 root/shared/project/work-item documents
were checked; an independent documentation review found no material authority or
release-gate contradiction. Independent harness review found and prompted fixes
for empty/skipped suites, a Python import-boundary bypass and mismatched
test-to-runner registration. Negative fixture tests protect those cases.

Local run summaries are retained under .local/foundation-verification and
individual case artifacts under .local/harness. The LiveKit stack remains a
verified candidate selection: no SDK dependency install, application lockfile,
Compose deployment, actual room smoke or real-model run is claimed here.
TypeScript import scanning remains a structural heuristic; future compiler
and behavioral checks are required. This foundation and its tests were produced
with AI assistance and independent agent reviews.

Next product checkpoint is one independent worker and persisted fake supplier
inquiry, with a controlled crash after supplier inquiry success and recovery.
It leaves the booking unchanged. Collaborative learning keeps an explain,
attempt, review, change cycle and records assistance accurately.
