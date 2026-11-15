# Contributing to the ecosystem

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe how people and coding agents plan, build, check and hand off a change |
| Audience | Contributors and coding agents preparing a change for review or handoff |
| Scope | Planning, engineering expectations, evidence, installed-package and usability checks, and handoff; full agent rules live in AGENTS.md |
| Owns | Contributor workflow, quality gates and review expectations |
| Related | [AGENTS.md](AGENTS.md) · [Validation plan](docs/validation-plan.md) · [Qualification gates](docs/qualification-gates.md) · [Local setup guide](local-setup/README.md) · [P1 public package guide](projects/agent-continuity/python/README.md) |

This guide describes the contributor workflow for people and coding agents: how
to plan a change, what the quality bar is, how to check built packages and gather
usability feedback, and what to run before handoff. Coding agents also follow the
full rules in [AGENTS.md](AGENTS.md).

## Plan the change

1. Before writing code, read [AGENTS.md](AGENTS.md), the relevant Design.md, the
   relevant scope document ([portfolio scope](docs/portfolio-scope.md) and project
   charter) and the [build plan](docs/build-plan.md) work package.
2. Select the acceptance IDs and define the smallest coherent slice.
3. Record the failure cases.

## Engineering expectations

| Area | Expectation |
| --- | --- |
| Interfaces | Keep public interfaces typed and cross-language payloads runtime-validated |
| Tests | Add meaningful tests and a negative fixture for each new guard |
| Standards | Follow the [design template](docs/design-template.md), the [Python practices](docs/python-engineering.md) and the applicable [engineering gates](docs/validation-plan.md) |
| Environments | Use the frozen Python and TypeScript environments and exact image pins |
| Docs, schemas and migrations | Update them with the implementation |
| Data, resources and authority | Preserve existing data, bound resources and follow the case authority and confirmation boundaries |
| Prose | Keep secrets, private project references and literal source identifiers out of prose |
| Attribution | Record assistance and contributions accurately |

The [local setup guide](local-setup/README.md) documents startup, credentials,
smoke checks and explicit reset behavior.

## What counts as evidence

- A task needs ordinary, failure and useful-progress assertions, plus safe log and
  exception evidence.
- A passing unrelated suite or a coverage percentage does not close a task's
  acceptance criteria.
- Preserve planned status for missing product behavior.
- Local infrastructure checks do not establish real model quality or durable
  execution.

## Installed consumer and feedback workflow

### Check the built P1 package

1. Begin with the [P1 public package guide](projects/agent-continuity/python/README.md)
   and complete its documented bootstrap.
2. Run `make p1-package-check`. The check builds the wheel and source distribution
   (sdist), rebuilds the sdist and executes isolated installed examples.
3. Preserve its report and exact artifact.

- Do not add a checkout to `PYTHONPATH`.
- The examples in `projects/agent-continuity/examples` cover inquiry, resource
  ownership and the explicit PostgreSQL consumer.
- The PostgreSQL artifact example verifies declared extras and controlled startup
  failure. Actual store behavior requires the separately documented
  restricted-role PostgreSQL lane.
- P2 and P3 packages must prove their own built artifacts.

### Run a usability review

Ask a developer to follow the README from a fresh environment without a guided
walkthrough. Record:

- the runtime and platform;
- the artifact;
- the steps;
- the setup time;
- missing prerequisites;
- the smallest working example;
- how they interpreted failures.

The review asks one key question: can the caller distinguish retrying an original
request from reconciliation, input correction, capacity deferral and stopping
after uncertain external effects? A cancellation receipt alone must never be
interpreted as stopped supplier work.

### Record the feedback

- Keep the feedback, the observed API or documentation problem, the chosen
  revision or justified no-change decision, and its regression evidence in the
  relevant work item.
- Use synthetic inputs and redact credentials before retaining diagnostics.
- Automated agent review and isolated installs are useful separate evidence.
  Neither is first-time human feedback.
- Human usability evaluation stays planned until it is performed.

## Before handoff

Run the narrow checks first, then the applicable integration lane, then the full
fast harness. For handoff, run these checks:

| Check | Command | What it proves | When to run |
| --- | --- | --- | --- |
| Python suites | `make test` | The root and all three project Python suites | Every handoff |
| Shared checks | `make check` | Shared static, correctness and typing checks | Every handoff |
| Formatting | `make format-check` | Python formatting with Ruff | Every handoff, as a separate run |
| Frontend | `make frontend-check` | TypeScript, Vitest, formatting and production builds | When frontend behavior changes |
| PostgreSQL, process, package and media gates | The applicable gate in the [qualification gates guide](docs/qualification-gates.md) | The behavior that gate covers | When that behavior changes |

Report what ran and what remains unverified. No remote continuous integration
(CI) is required.
