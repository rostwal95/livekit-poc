# Granular phasewise implementation planning

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for granular phasewise implementation planning |
| Audience | Engineers selecting or sequencing implementation tasks; coding agents |
| Scope | Shared roadmap and three subordinate project task plans; excludes product capabilities and executable acceptance evidence |
| Owns | Change plan, observed verification and handoff for the granular implementation plan |
| Related | [Work item 0004](0004-plan-and-showcase-audit.md) · [Work item 0006](0006-design-and-engineering-gates.md) · [Granular roadmap](../implementation-plan.md) · [Build plan](../build-plan.md) |

## Behavior and scope

Decompose the audited three-project build plan into actionable phase gates and
bounded tasks. Preserve all 22 PLAN work packages and 54 acceptance IDs. Reuse the
implemented foundation and keep new task estimates separate from historical
estimates and observed product evidence. This work implements planning documents,
not product capabilities.

## Interfaces and ownership

| Document | Owns |
| --- | --- |
| Build plan | Work-package ordering |
| New [granular roadmap](../implementation-plan.md) | Cross-project task gates and shared support work |
| Three subordinate project plans | Task prerequisites, deliverables, failure assertions, UI and telemetry evidence, acceptance contribution and preliminary effort |
| Charters | Requirements authority |

Reading order and corpus policy include the new plans.

## Failure cases and validation

Check that:

- every task ID is unique and defined
- all listed project prerequisites resolve
- explicit task dependencies have no cycle
- each acceptance traceability table matches its original charter

Preserve the existing primary PLAN coverage rows. Recompute task and hour totals,
and check relative links, metadata and documentation rules. Run the full fast lane
after shared instruction or policy changes. Product cases must remain planned. A
plan cannot create executable acceptance evidence.

## Results and handoff

Created the shared roadmap and three project plans: 74 project tasks, seven
remaining shared tasks and one recorded shared checkpoint. Preliminary direct
engineering sizing reconciles to 210–329 hours before contingency and learning.
All 54 charter rows and the original 22-package primary mapping remain intact.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Traceability | Traceability audit | Contiguous unique task IDs, all task references resolved, matching 20/17/17 charter rows (P1/P2/P3) and an acyclic explicit dependency graph, including the conditional integrated-route edges |
| Documentation | Documentation checks | 57 maintained documents, zero policy or link violations |
| Fast lane | Full fast lane | 121 Python tests passed with zero skips; static checks and Ruff passed; mypy passed for nine source files |
| Formatting | Format verification | 38 files passed |
| Catalog | Harness validation | 55 catalog cases, one registered baseline runner |
| Deep gate | Deep result | Incomplete with exit 2: one baseline passed and all 54 product cases remain not implemented |
| Whitespace | Working diff whitespace check | Passed |

Contract gate expansions are recorded as audit assumptions, not proof of
implementation. These plans add no product acceptance evidence. No application
source, dependency lock or running infrastructure changed. Frontend and runtime
checks were not repeated.

### Evidence and next step

Ignored evidence lives under `.local/validation/granular-plan`:

| Artifact | Content |
| --- | --- |
| `traceability.json` | Traceability audit |
| `fast.txt` | Full fast lane output |
| `format.txt` | Format verification output |
| `deep.json` | Deep result |

Planning used AI assistance and separate per-project reviews. Review corrections
cover shared migration privileges, immutable acceptance metadata, standalone versus
integrated P3 routing, early UI projection sequencing, earlier P2 package proof and
partial acceptance wording.

Begin with P1 implementation task P1-I01, followed by the schema-safe inquiry and
recovery slice P1-I02 through P1-I07. Its first proof is a real CLI and store
recovery demonstration. Observed UI states also require shared task S-I04.
Permission-dependent media, platform and portfolio release evidence remain
explicit and non-passing until observed.
