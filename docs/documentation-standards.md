# Ecosystem documentation standards

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define one structure, metadata form and table style for every maintained document |
| Audience | People and coding agents who write, review or validate repository documentation |
| Scope | The maintained corpus listed in `harness/documentation.json`; generated artifacts and ignored local state are excluded |
| Owns | Document card, required sections and tables by role, formatting, terminology, links and documentation checks |
| Related | [Documentation map](README.md) · [Design template](design-template.md) · [Work item template](work-items/template.md) · [Harness guide](../harness/README.md) |

## Overview

The documentation must let a person or coding agent understand scope, locate
authority, run supported commands and tell implemented behavior apart from a
requirement. Keep each topic authoritative in one place and link to it elsewhere.

| Principle | Rule |
| --- | --- |
| One owner per topic | Each topic is authoritative in exactly one document; others link to it |
| Same shape for the same role | Documents of one role share sections, card fields and table layouts |
| Tables for structured facts | Commands, options, limits, components, statuses, gates and links go in tables |
| Prose for reasoning | Use short paragraphs for rationale, trade-offs and narrative explanation |
| Facts over promises | State observed evidence, keep caveats, and label planned work as planned |

## Corpus and authority

### Corpus

| Included | Excluded |
| --- | --- |
| Root README, AGENTS, Design and CONTRIBUTING | Generated artifacts and build output |
| Harness Markdown and shared docs directly under `docs` | Ignored local state such as `.local` |
| Project charters, work items, decisions and task plans | Material outside the executable inventory |
| Project, service, application, contract and local-setup onboarding | Vendor notices under application `public` folders |

The inventory and role rules live in `harness/documentation.json`.

### Document ownership

| Document | Owns |
| --- | --- |
| Root README.md | Ecosystem purpose, current capabilities, requirements, quickstart and navigation |
| Root AGENTS.md | Agent reading order, owned paths, development rules and verification |
| Root Design.md | Shared data flow, state authority, interfaces and failure boundaries |
| CONTRIBUTING.md | Contributor workflow, quality gates and review expectations |
| docs/README.md | Documentation map for every maintained document |
| docs/portfolio-scope.md | V1 boundaries, execution modes and release definitions |
| docs/projects/*-scope.md | Project requirements and stable acceptance IDs |
| docs/build-plan.md | Authoritative PLAN work-package sequence, dependencies and estimate history |
| docs/implementation-plan.md and docs/implementation | Subordinate granular task decomposition, phase gates, effort sizing and per-task handoff |
| docs/validation-plan.md | Test lanes, required fault scenarios, benchmarks and evidence |
| docs/technology-baseline.md | Candidate versions, compatibility, promotion and updates |
| harness documentation and foundation.json | Actual harness commands, product/foundation source contracts and outcome semantics |
| contracts onboarding | Shared producer/consumer fixtures, compatibility and data-only ownership |
| docs/decisions | Reviewed architecture choices and their rationale |
| docs/demo-plan.md | Capability demonstrations and honest observable UI transitions |
| docs/observability.md | Current/future signals, safe errors, cardinality and operational evidence |
| docs/local-real-inference.md | Explicit prepared local model/engine operations, isolation, resource headroom and qualification boundaries |
| docs/provider-demo.md | Opt-in provider setup/check/start/stop, private credential boundaries, declared pipeline and fresh provider qualification |
| docs/python-engineering.md | Python API, typing, async/resource, persistence, diagnostics and package engineering practices |
| docs/design-template.md | Standard design authoring structure; never implementation evidence |
| docs/plan-audit.md | Reviewed findings, implemented corrections and remaining limits |
| Project README.md, Design.md and AGENTS.md | Product onboarding, implementation boundaries and agent workflow |
| local-setup documentation | Actual lifecycle commands, host/container networking, image pins, readiness and smoke boundaries |
| Service and application onboarding | Implemented runtime behavior, owned interfaces, resource limits and validation |
| docs/work-items | Concrete change plans, observed verification and handoffs |

### Resolving conflicts

| Question | Authoritative source |
| --- | --- |
| What must exist | Scope (portfolio scope and project charters) |
| Who owns state and boundaries | Design |
| In what order work happens | Build plan |
| What counts as sufficient evidence | Validation plan |

Resolve a conflict in the authoritative document and update dependent summaries
together.

## Document card and filenames

### Filenames

Use `README.md`, `Design.md` and `AGENTS.md` with that exact casing. Keep
existing paths: the harness requires many documents at fixed locations.

### Document card

Every corpus document has exactly one descriptive H1 and, between the H1 and the
first H2, one document card. The card is a two-column `Field | Value` table with
exactly these six rows, in this order:

| Field | Meaning | Example value |
| --- | --- | --- |
| Status | Document status from the table below | Active |
| Purpose | One sentence: what the document is for | Explain how P2 accepts and dispatches channel input |
| Audience | Who should read it | Engineers changing P2 dispatch; coding agents |
| Scope | What it covers and, briefly, what it excludes | P2 TypeScript library; excludes the joined showcase |
| Owns | The topics this document is authoritative for | P2 implementation boundaries and design decisions |
| Related | Two to five relative links, separated by ` · ` | Charter · README · Design, each as a relative link |

Rules:

- Write `Status:` only as the card's first row. A separate `Status:` line is
  rejected.
- Documents carry no review dates. Git history records when content changed, and
  the checker rejects `Last reviewed:` lines.
- Keep card values short and free of pipe characters.
- The root README may place its logo, badges and title above the card, inside a
  centered HTML block; the card still precedes the first H2.

### Status values

| Status | Meaning |
| --- | --- |
| Active | Current instructions, design, specification or maintained guide |
| Planned | A delivery plan or work item whose execution remains pending |
| Completed | A finished work item or audit with recorded outcomes |
| Template | A reusable starting structure, not completed evidence |

### Document status and implementation status

| Concept | Rule |
| --- | --- |
| Document status | Describes the document itself (card `Status` row) |
| Implementation status | Describes product capability; state it in the document body |
| Planned features | Active charters can describe planned features |
| Capability labels | Use the implementation status vocabulary below explicitly |

## Sections by role

Use the following H2 sections, in order, for each repeated document role. Extra
H2 sections may sit between them. H3 sections organize detail without creating a
second requirements owner. Sections listed under "Required tables" must contain a
populated pipe table.

| Role | Required sections | Required tables |
| --- | --- | --- |
| README.md | Overview; Implementation status; Documentation; Requirements; Commands; Validation; Next milestone | Implementation status; Documentation; Requirements; Commands; Validation; Next milestone |
| AGENTS.md | Read first; Owned paths; Development rules; Verification; Handoff | Read first; Owned paths; Verification |
| Design.md and design template | Overview; Objectives; Functional requirements; Non-functional requirements; Back-of-the-envelope calculations; High-level design; Sequence diagram; Low-level design; Components and related details; Security and privacy; Observability; Metrics; Exception handling; Design considerations and trade-offs; Validation and acceptance gates | Every section except Overview and the three diagram sections |
| Project charter | Overview; Implementation status; Ownership and dependencies; Required V1 behavior; Public contracts; Correctness and failure boundaries; Acceptance matrix; Development checkpoints; Release gates; Deferred scope; References | Acceptance matrix (parsed by the harness; rows stay byte-identical) |
| Work item | Behavior and scope; Interfaces and ownership; Failure cases and validation; Results and handoff | Criteria table in Behavior and scope; gate table in Failure cases and validation |
| Decision record | Context; Decision; Consequences; Alternatives considered; Validation; References (sections without content may be omitted) | None required; use tables for compared options |

### Design documents

Use the [design template](design-template.md) for each maintained Design.md.

| Topic | Rule |
| --- | --- |
| Requirement tables | Objectives and functional requirements distinguish business and technical rows; non-functional requirements state bounds or targets, units, verification and evidence status |
| Sizing | Separate configured limits, illustrative sizing, proposed experiment budgets and measured results; show inputs, formulas, results and exclusions |
| Diagrams | High-level design has a Mermaid `flowchart` or `graph` and a numbered explanation; sequence uses `sequenceDiagram`; low-level uses `classDiagram` or `stateDiagram-v2`; keep each closed, non-empty diagram inside its owning section |
| Component detail | Keep state ownership, interfaces, identity, transaction and failure boundaries, implementation layout and lifecycle under H3s in Components and related details |
| Operations detail | Add migration and restore, retention, security, operational recovery, compatibility and architecture decision record (ADR) or open-question detail where relevant |
| Data-only and tooling modules | Explain the actual surface rather than invent a runtime exporter or service |
| Producers | Logs, metrics and exceptions distinguish implemented producers from planned ones |
| Gates | Every gate names sufficient evidence and missing prerequisites |
| Shared authorities | Link the shared Python engineering and observability documents |

### Other shared guides

Other shared guides use topic-specific sections with the same card, writing and
table rules. Keep obsolete implementation roadmaps out of starter and learning
guides; link them to the build plan instead.

## Tables and formatting

### When to use a table

| Content | Format |
| --- | --- |
| Commands, options, limits, budgets, ports, versions, statuses, gates, components, files, terms, links | Table |
| A sequence of steps a reader performs | Numbered list, with code blocks for commands to copy |
| A short unordered set of rules or caveats (up to about five) | Bullet list |
| Rationale, trade-offs, narrative explanation | Short paragraphs |
| Runnable command sequences | Fenced code block with a language tag |

### Standard column sets

Use these headers so the same kind of table looks the same everywhere. Add a
column only when the content needs it.

| Content | Columns |
| --- | --- |
| Capability status | Capability · Status · Evidence |
| Documents | Document · Purpose |
| Requirements | Requirement · Version or value · Notes |
| Commands | Task · Command · Notes |
| Options and settings | Option · Default · Allowed values · Description |
| Limits and budgets | Limit · Value · Applies to · Notes |
| Components and files | Component · Path · Responsibility · Status |
| Validation | Check · Command · What it proves · Status |
| Terms | Term · Meaning |
| Milestones | Step · Outcome · Gate |
| Rules in AGENTS files | Rule area · Rule (one rule per row or bullet) |

### Implementation status vocabulary

| Label | Meaning |
| --- | --- |
| Qualified | Implemented and passed its selected gate with retained evidence |
| Implemented | Code and tests exist; no selected qualification yet |
| Partial | Some of the capability exists; the gap is named |
| Planned | Not implemented |
| Not qualified | Implemented but explicitly not qualified (for example `local_real`) |

### Table conventions

| Convention | Rule |
| --- | --- |
| Cell length | Keep cells to a phrase or one short sentence; move explanation below the table |
| Code and names | Put commands, paths, option names and identifiers in backticks |
| Pipes in cells | Escape a literal pipe as `\|` |
| Empty cells | Avoid them; write "None" or "Not applicable" |
| Ordering | Order rows by workflow, then by importance; keep acceptance matrices in ID order |
| Links | Use relative links for repository files |

## Terminology and evidence

### Projects, scope and release gates

| Term | Rule |
| --- | --- |
| Project names | Use the three project names and P1/P2/P3 identifiers consistently |
| M1 | Refers only to existing confirmed-investigation intake |
| V1 | Refers to the fixed project scope |
| Execution modes | Use offline, lab and live |
| Release gates | Use Local-ready V1 and Portfolio-ready V1 |

### Lab and inference profiles

In these rules, the G scripted profile is the P1 Phase G scripted media profile,
and POC means proof of concept.

| Profile or fact | Rule |
| --- | --- |
| Shared lab | Uses actual LiveKit with deterministic text and audio diagnostics and a browser console |
| Evidence path | Record which native-client, container or browser path each check exercised; native SDK reception does not establish browser playback |
| Default transport lab | Performs no speech recognition, reasoning or synthesis |
| G scripted profile | Uses declared fixtures rather than general inference |
| `local_real` | Implements prepared local Whisper/Qwen/Piper inference; actual engine, model and media qualification is tracked separately |
| `provider_real` | Uses Deepgram/OpenAI/ElevenLabs with native-only private keys; the selected v2 gate passed both actual browser cases with cleanup, and P1 V1 is qualified for the local POC with it |
| Specialist analysis | Current P3 policy and image capabilities use bounded deterministic fixtures; general model-based specialist reasoning remains planned |
| Product scenarios | Working infrastructure does not complete any of the 54 product scenarios (55 catalog definitions including the baseline) |

### Identities and scope

- Keep session, conversation, case, workflow, delegation, execution attempt,
  effect and delivery identities distinct.
- Provider-account scope and verified business account scope are different
  concepts.
- Case authority, execution, channel and delegation ownership follow the root
  design.

### Evidence language

- Use exact assertions for deterministic behavior.
- Model judgments cannot replace database or effect checks.
- Document actual observations, unknown outcomes and test limits.
- Avoid subjective alignment scores, line-count targets, unconditional latency
  promises and unsupported exactly-once claims.

## Commands, links and references

| Area | Rule |
| --- | --- |
| Command context | State the working directory and prerequisites for commands |
| Quickstarts | Only verified existing commands belong in runnable quickstarts |
| Future interfaces | Clearly label future interfaces and commands as planned |
| Incomplete gates | Document expected non-zero outcomes |
| Safety | Avoid hidden setup, implicit paid-service calls and destructive normal shutdowns |
| Local links | Use relative links within the repository, including HTML `src`, `href`, `poster` and `srcset` targets |
| External claims | Link public official documentation, package metadata or versioned releases |
| Provenance | Keep prose free of internal project provenance, private repository links and literal source-control identifiers; use release-based source URLs |
| Machine evidence | Code snapshot identifiers and lock/image checksums can remain in machine run evidence when reproducibility requires them |
| Examples | Use synthetic data |
| Privacy | Keep secrets, personal local paths and unrelated business or project details out of ecosystem documentation |
| Authorship | Retain accurate assistance and authorship statements where they affect portfolio claims |

## Validation and maintenance

### Running the checks

Run from the repository root. Prepare the frozen Python environment with all
declared extras and development dependencies before the full fast lane; its
implemented service tests require those dependencies. The documentation checker
itself is dependency-free.

```sh
uv sync --frozen --all-extras --dev
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

### What the checker enforces

| Check | Rule |
| --- | --- |
| Corpus | Every required document exists; include patterns add the rest |
| Title | Exactly one H1 |
| Document card | One `Field \| Value` card with the six rows in order, before the first H2; supported Status value; no empty values |
| Legacy metadata | No `Status:` or `Last reviewed:` lines outside code examples |
| Role sections | Required H2 sections present; ordered and unique for designs |
| Role tables | Each required-table section contains a populated pipe table |
| Design diagrams | Section-owned Mermaid diagrams of the required types |
| Fences | Every fenced code block is closed |
| Links | Markdown links and HTML `src`, `href`, `poster` and `srcset` targets resolve inside the repository |
| Prohibited references | Forbidden terms and source-identifier patterns are absent |

The checker is a structural Markdown subset, not a renderer. It does not prove
diagram syntax or meaning, validate external websites or establish product
behavior.

### Evidence and review

| Area | Rule |
| --- | --- |
| Docker, browser and lab evidence | Document it separately from unit or structural checks; a passing lab smoke establishes only its declared transport, readiness and intake checks |
| Model quality and release | Require their own evidence |
| Operational commands | Keep environment setup, safe lifecycle behavior and operational commands in the local-setup guide rather than duplicating divergent instructions |
| Human review | Checks semantics, diagram meaning, scope, authority, commands, quantitative assumptions and roadmap coherence; parse Mermaid separately when diagrams change |
| New rules | Every new documentation rule needs positive and negative tests |
