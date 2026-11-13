# Contributing to the ecosystem

Status: Active
Last reviewed: 10 November 2026

Read AGENTS.md, the relevant Design.md, scope and build-plan package before code.
Select acceptance IDs, define the smallest coherent slice and record failure
cases. Keep public interfaces typed and cross-language payloads runtime-validated.
Add meaningful tests and a negative fixture for each new guard. Follow the
[design template](docs/design-template.md), [Python practices](docs/python-engineering.md)
and applicable [engineering gates](docs/validation-plan.md). A task needs ordinary,
failure and useful-progress assertions plus safe log/exception evidence; a passing
unrelated suite or a coverage percentage does not close its acceptance criteria.

Use the frozen Python/TypeScript environments and exact image pins. Run the narrow
checks, applicable integration and full fast harness before handoff. Preserve
planned status for missing product behavior. Local infrastructure checks do not
establish real model quality or durable execution.

Update docs, schemas and migrations with implementation. Preserve existing data,
bound resources and follow case authority/confirmation boundaries. Keep secrets,
private project references and literal source identifiers out of prose. Record
assistance and contributions accurately. The local-setup guide documents startup,
credentials, smoke checks and explicit reset behavior.

## Installed consumer and feedback workflow

Begin with the [P1 public package guide](projects/agent-continuity/python/README.md)
and run make p1-package-check after its documented bootstrap. This builds the
wheel/sdist, rebuilds the sdist and executes isolated installed examples. Preserve
its report and exact artifact; do not add a checkout to PYTHONPATH. The examples
in projects/agent-continuity/examples cover inquiry, resource ownership and the
explicit PostgreSQL consumer. The PostgreSQL artifact example verifies declared extras and controlled startup
failure; actual store behavior requires the separately documented restricted-role
PostgreSQL lane. Future P2/P3 packages must prove their own built artifacts.

For usability review, ask a developer to follow the README from a fresh environment
without a guided walkthrough. Record runtime/platform, artifact, steps, setup time,
missing prerequisites, the smallest working example and failure interpretation.
Can the caller distinguish retrying an original request from reconciliation,
input correction, capacity deferral and stopping after uncertain external effects?
A cancellation receipt alone must never be interpreted as stopped supplier work.

Keep feedback, the observed API/docs problem, the chosen revision or justified
no-change decision, and its regression evidence in the relevant work item. Use
synthetic inputs and redact credentials before retaining diagnostics. Automated
agent review and isolated installs are useful separate evidence; neither is
first-time human feedback. Human usability evaluation is planned until performed.

For handoff, run make test for root and all three project Python suites, make check for shared static,
correctness and typing, and make format-check separately. Run make frontend-check
and the applicable PostgreSQL/process/package/media gates when their behavior
changes. Report what ran and what remains unverified; no remote CI is required.
