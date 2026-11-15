# Implementation work item template

| Field | Value |
| --- | --- |
| Status | Template |
| Purpose | Give each substantial implementation slice the same plan, validation and handoff structure |
| Audience | Engineers and coding agents who plan, validate or hand off an implementation slice |
| Scope | The work-item card, the four required sections and their tables; excludes completed evidence |
| Owns | Standard work-item structure; never implementation evidence |
| Related | [Validation plan](../validation-plan.md) · [Design template](../design-template.md) · [Documentation standards](../documentation-standards.md) · [Build plan](../build-plan.md) |

Copy this structure for a substantial implementation slice. Replace every
placeholder with concrete contracts and commands. Do not treat example fields as
evidence.

Start every new work item with a descriptive H1 and this document card. A new
work item starts as Planned because its execution remains pending; set Status to
Completed once its outcomes are recorded. Replace each value, keep values short
and free of pipe characters, and use two to five relative links in Related.

```markdown
# Descriptive title of the change

| Field | Value |
| --- | --- |
| Status | Planned |
| Purpose | One sentence: the behavior this slice delivers |
| Audience | Who reads it, for example engineers changing P2 dispatch; coding agents |
| Scope | The task and acceptance IDs it covers; briefly, the deferred work it excludes |
| Owns | This slice's change plan, observed verification and handoff |
| Related | [P1 charter](../projects/agent-continuity-scope.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [P1 design](../../projects/agent-continuity/Design.md) |
```

## Behavior and scope

State:

- the user/developer behavior;
- the implementation task/PLAN and acceptance IDs;
- the current baseline and the smallest coherent change;
- the owned paths and explicit deferred work.

Select the applicable engineering gates from the
[validation plan](../validation-plan.md).

### Terms used in this record

Define each task ID, acceptance ID and abbreviation the record uses.

| Term | Meaning |
| --- | --- |
| ID or abbreviation used in this record | One short sentence that defines it |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Existing requirement ID | Principal, state, revision and dependency contract | Public action and exact fault schedule | Persisted/external invariant and forbidden effects | Eligible expected outcome | Real/fake adapter, timeout, command and artifact |

## Interfaces and ownership

Name:

- the public types;
- the authoritative state owner and identities;
- schema/migration changes;
- the commitment/cancellation boundary;
- affected dependencies.

List the affected components and files:

| Component | Path | Responsibility | Status |
| --- | --- | --- | --- |
| Public type, adapter or store | Repository-relative path in backticks | State, identity or boundary it owns | Implementation status, such as Planned |

Link the relevant design and charter.

## Failure cases and validation

List:

- deterministic scenarios and exact assertions;
- failpoints/barriers and prerequisites;
- expected exits and artifact paths.

Write the exact existing validation commands. Separate offline correctness from
actual media and live-model evidence.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY through G-RELEASE as relevant | State applicability rather than silently omit a check | Ordinary, negative and useful-progress assertions | Actual store/process/media/provider requirement | Required unavailable/skipped/zero-test/timeout is non-passing |

Also record:

- log event/field/severity, safe exception code, retry/reconciliation and
  metric-unit/label expectations;
- secret-sentinel/redaction, cancellation, resource cleanup and telemetry-outage
  tests, where relevant.

Engineering rules for the slice:

- Type new Python public boundaries.
- Keep transactions short.
- Add new packages to test/lint/type discovery.
- Update Design.md through the [standard template](../design-template.md).
- Review applied versus uncertain external effects explicitly. Transport retry
  advice grants no authority.

## Results and handoff

Record:

- implemented behavior and observed results;
- code/API review findings;
- limitations and decisions;
- assistance;
- the next bounded step.

Record each executed check with its observed outcome:

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Exact gate, lane or suite | Exact command that ran | Assertions it established and their limits | Observed outcome, including failed or not run |

Include failing or unimplemented checks. Update README/capability status only when
evidence supports the change.
