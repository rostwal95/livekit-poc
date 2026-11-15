# Documentation audit and ecosystem build plan

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the documentation audit and the ecosystem build plan |
| Audience | Documentation maintainers and reviewers; coding agents |
| Scope | Ecosystem documentation corpus, its structural checks and the detailed build plan; excludes product behavior and generated artifacts |
| Owns | Change plan, observed verification and handoff for the documentation audit |
| Related | [Work item 0001](0001-portfolio-foundation.md) · [Work item 0003](0003-local-project-foundation.md) · [Build plan](../build-plan.md) · [Documentation standards](../documentation-standards.md) |

## Behavior and scope

Standardize the ecosystem corpus, remove unrelated provenance and literal source
identifiers, resolve specification and roadmap drift, and establish one detailed
build plan. Preserve existing product behavior and all 54 acceptance IDs.

## Interfaces and ownership

| Component | Responsibility |
| --- | --- |
| Root and repeated project documents | Use common role templates |
| Documentation manifest | Defines the audited corpus and quality rules |
| Static harness | Invokes its checker through the docs group |

Generated artifacts remain outside the versioned ecosystem documentation corpus.

## Failure cases and validation

Verify metadata, required sections, local targets, code fences, safe paths and
reference forms. Negative fixtures must catch missing or invalid metadata, broken
links, unwanted references and source-identifier links. They must still accept
versioned release links and ordinary database-commit language. Check build
dependency order, all acceptance mappings, current commands and incomplete-gate
semantics.

## Results and handoff

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Fast lane | Complete fast lane | 50 tests passed: 10 intake, 11 acceptance-runner, 14 structural and 15 documentation tests |
| Documentation | Corpus checker | 30 ecosystem documents passed with zero violations |
| Catalog metadata | Harness metadata validation | The existing baseline plus 54 planned product scenarios validated |
| Deep gate | Deep gate, which runs the acceptance catalog | Incomplete with exit 2: one passing baseline and 54 not_implemented cases |
| Traceability | Traceability checks | Confirmed 54 unique charter IDs, 54 primary coverage rows and 22 defined work packages |
| Provenance | Separate scan of the ecosystem Markdown corpus | No prohibited provenance or literal source identifiers found |

Independent semantic review checked section order, state authority, migration
sequencing, release gates and candidate-stack limits. Public metadata links
resolve by release tag.

The checker additionally rejects unsafe URI schemes, absolute local links and
dangling documentation links. It does not resolve section fragments, verify
external site availability or establish prose semantics. Those remain manual
review responsibilities.

### Evidence and next step

Diagnostic reports are retained under the ignored `.local/documentation-audit`
directory. Generated artifacts are outside this corpus. This documentation and
harness work used AI assistance and independent reviews.

No worker, channel, delegation or Compose capability is implemented by this work.
Follow work packages PLAN-01 through PLAN-03 in the
[build plan](../build-plan.md) for the next inquiry and recovery slice. Preserve
the current M1 baseline (the original SQLite confirmed-investigation intake) and
investigation-only permission.
