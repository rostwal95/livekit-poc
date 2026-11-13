# Implementation work item template

Status: Template
Last reviewed: 9 November 2026

Copy this structure for a substantial implementation slice. Replace placeholders
with concrete contracts and commands; do not treat example fields as evidence.

## Behavior and scope

State the user/developer behavior, implementation task/PLAN and acceptance IDs.
Identify the current baseline, smallest coherent change, owned paths and explicit
deferred work. Select applicable engineering gates from the validation plan.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Existing requirement ID | Principal, state, revision and dependency contract | Public action and exact fault schedule | Persisted/external invariant and forbidden effects | Eligible expected outcome | Real/fake adapter, timeout, command and artifact |

## Interfaces and ownership

Name the public types, authoritative state owner, identities, schema/migration
changes, commitment/cancellation boundary and affected dependencies. Link the
relevant design and charter.

## Failure cases and validation

List deterministic scenarios, exact assertions, failpoints/barriers, prerequisites,
expected exits and artifact paths. Write the exact existing validation commands.
Separate offline correctness from actual media and live-model evidence.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY through G-RELEASE as relevant | State applicability rather than silently omit a check | Ordinary, negative and useful-progress assertions | Actual store/process/media/provider requirement | Required unavailable/skipped/zero-test/timeout is non-passing |

Record log event/field/severity, safe exception code, retry/reconciliation and
metric-unit/label expectations. Include secret-sentinel/redaction, cancellation,
resource cleanup and telemetry-outage tests where relevant. Type new Python
public boundaries, keep transactions short and add new packages to test/lint/type
discovery. Update Design.md through the standard template. Review applied versus
uncertain external effects explicitly; transport retry advice grants no authority.

## Results and handoff

Record implemented behavior, observed results, code/API review findings,
limitations, decisions, assistance and the next bounded step. Include failing or
unimplemented checks. Update README/capability status only when evidence supports
the change.
