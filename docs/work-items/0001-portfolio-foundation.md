# Portfolio scope and harness foundation

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the portfolio scope and harness foundation |
| Audience | Engineers and reviewers tracing the portfolio and harness foundation; coding agents |
| Scope | V1 project scopes, local execution modes, stack policy, agent workflow and harness bootstrap; excludes the worker, channel SDK and delegation runtime |
| Owns | Change plan, observed verification and handoff for the portfolio foundation |
| Related | [Work item 0002](0002-documentation-audit.md) · [Portfolio scope](../portfolio-scope.md) · [Harness guide](../../harness/README.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

The requested change fixes the three V1 project scopes, local execution modes,
latest-compatible stack policy and AI coding agent workflow. It adds documentation
and a harness bootstrap. It does not implement the worker, channel SDK or
delegation runtime.

### Change boundaries

- Preserve the existing M1 intake code (the original SQLite
  confirmed-investigation intake) and its investigation-only permission model.
- Define the product acceptance requirements listed under
  [Interfaces and ownership](#interfaces-and-ownership) as pending.
- Add root and project AGENTS.md, Design.md and README.md files with ownership,
  design boundaries and exact implemented commands.
- Add an acceptance catalog and runner, module and rule checks, fast and deep
  entry points, and negative harness tests.
- Record exact upstream stable candidate versions. Require clean resolution,
  native import and actual-room checks before stack validation.

### Evidence before changes

The existing 10 intake tests passed on Python 3.14.10. P1 M1 is the only product
implementation.

## Interfaces and ownership

The change defines these pending product acceptance requirements:

| Project | Acceptance requirements | Status |
| --- | --- | --- |
| [P1 (Agent Continuity Lab)](../projects/agent-continuity-scope.md) | P1-01 through P1-20 | Pending |
| [P2 (Channel Continuity Kit)](../projects/channel-continuity-scope.md) | P2-01 through P2-17 | Pending |
| [P3 (Delegation Reliability Kit)](../projects/delegation-reliability-scope.md) | P3-01 through P3-17 | Pending |

## Failure cases and validation

Run current intake and harness tests, validate metadata and all documentation
links, run the fast lane, inspect a baseline execution report, and deliberately
run a pending project gate. The pending gate must return an incomplete, nonzero
result. Verify focused and conservative changed-file selection. Keep unrelated
resume, interview-guide and artifact files untouched.

## Results and handoff

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Fast lane | Full fast lane | 35 tests passed: 10 intake, 11 acceptance-runner and 14 structural-checker tests |
| Catalog metadata | Harness metadata validation | 55 cases validated: the registered M1 baseline and 54 planned product requirements |
| Focused selection | Focused P2 checks | Selected only P2 |
| Changed-file selection | Changed-file run without a usable Git baseline | Conservatively selected all three modules |
| Deep gate | Deep lane | Incomplete with exit 2: one passing baseline and 54 not_implemented cases |
| Documentation | Local link and code-fence check | All local links and code fences checked in 25 root, shared, project and work-item documents |

The incomplete deep-lane result is expected. It confirms that product scope is not
being presented as completed behavior.

An independent documentation review found no material authority or release-gate
contradiction. Independent harness review found and prompted fixes for empty or
skipped suites, a Python import-boundary bypass and mismatched test-to-runner
registration. Negative fixture tests protect those cases.

### Evidence and next step

Local run summaries are retained under `.local/foundation-verification` and
individual case artifacts under `.local/harness`. The LiveKit stack remains a
verified candidate selection. No SDK dependency install, application lockfile,
Compose deployment, actual room smoke or real-model run is claimed here.
TypeScript import scanning remains a structural heuristic. Future compiler and
behavioral checks are required. This foundation and its tests were produced with
AI assistance and independent agent reviews.

The next product checkpoint is one independent worker and persisted fake supplier
inquiry, with a controlled crash after supplier inquiry success and recovery. It
leaves the booking unchanged. Collaborative learning keeps an explain, attempt,
review, change cycle and records assistance accurately.
