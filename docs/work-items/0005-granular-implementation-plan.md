# Granular phasewise implementation planning

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Decompose the audited three-project build plan into actionable phase gates and
bounded tasks. Preserve all 22 PLAN work packages and 54 acceptance IDs. Reuse the
implemented foundation and keep new task estimates separate from historical
estimates and observed product evidence. This work implements planning documents,
not product capabilities.

## Interfaces and ownership

The build plan retains work-package ordering; the new granular roadmap owns
cross-project task gates and shared support work. Three subordinate project plans
own task prerequisites, deliverables, failure assertions, UI/telemetry evidence,
acceptance contribution and preliminary effort. Charters remain the requirements
authority. Reading order and corpus policy include the new plans.

## Failure cases and validation

Check every task ID is unique/defined, all listed project prerequisites resolve,
explicit task dependencies have no cycle, and each acceptance traceability table
matches its original charter. Preserve the existing primary PLAN coverage rows.
Recompute task/hour totals and check relative links, metadata and documentation
rules. Run the full fast lane after shared instructions/policy changes. Product
cases must remain planned; a plan cannot create executable acceptance evidence.

## Results and handoff

Created the shared roadmap and three project plans: 74 project tasks, seven
remaining shared tasks and one recorded shared checkpoint. Preliminary direct
engineering sizing reconciles to 210–329 hours before contingency and learning.
All 54 charter rows and the original 22-package primary mapping remain intact.

Observed validation:

- Traceability audit: contiguous unique task IDs, all task references resolved,
  matching 20/17/17 charter rows and an acyclic explicit dependency graph,
  including the conditional integrated-route edges. Contract gate expansions are
  recorded as audit assumptions, not proof of implementation.
- Documentation: 57 maintained documents, zero policy/link violations.
- Full fast lane: 121 Python tests passed, zero skips, static checks and Ruff
  passed; mypy passed for nine source files; 38 files passed format verification.
- Harness validation: 55 catalog cases, one registered baseline runner. Deep
  result remains incomplete with exit 2: one baseline passed and all 54 product
  cases remain not implemented. These plans add no product acceptance evidence.
- Working diff whitespace check passed. No application source, dependency lock
  or running infrastructure changed; frontend/runtime checks were not repeated.

Ignored evidence lives under .local/validation/granular-plan: traceability.json,
fast.txt, format.txt and deep.json. Planning used AI assistance and separate
per-project reviews. Review corrections cover shared migration privileges,
immutable acceptance metadata, standalone versus integrated P3 routing, early UI
projection sequencing, earlier P2 package proof and partial acceptance wording.

Begin P1-I01, followed by the schema-safe inquiry/recovery slice P1-I02 through
P1-I07. Its first proof is a real CLI/store recovery demonstration; observed UI
states also require shared S-I04. Permission-dependent media, platform and
portfolio release evidence remain explicit and non-passing until observed.
