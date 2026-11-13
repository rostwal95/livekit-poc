# Ecosystem documentation standards

Status: Active
Last reviewed: 12 November 2026

The documentation must let a person or coding agent understand scope, locate
authority, run supported commands and distinguish implemented behavior from a
requirement. Keep each topic authoritative in one place and link to it elsewhere.

## Corpus and authority

The ecosystem corpus includes root onboarding and CONTRIBUTING.md, harness
Markdown, shared docs directly under docs, project charters, work items, project
onboarding, local-setup Markdown, and the service/application onboarding under
services and apps, shared-contract onboarding under contracts, and architecture
decisions under docs/decisions and subordinate task plans under docs/implementation.
Generated artifacts, ignored local state and material outside that executable inventory are not part of the maintained corpus. The inventory
and role rules live in harness/documentation.json.

| Document | Owns |
| --- | --- |
| Root README.md | Ecosystem purpose, current capabilities, requirements, quickstart and navigation |
| Root AGENTS.md | Agent reading order, owned paths, development rules and verification |
| Root Design.md | Shared data flow, state authority, interfaces and failure boundaries |
| CONTRIBUTING.md | Contributor workflow, quality gates and review expectations |
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

Scope decides what must exist. Design decides authority and boundaries. The build
plan sequences implementation. Validation defines sufficient evidence. Resolve a
conflict in the authoritative document and update dependent summaries together.

## Metadata and filenames

Use README.md, Design.md and AGENTS.md with that exact casing. Every corpus
document starts with exactly one descriptive H1, one Status line and one Last
reviewed line. Use a date such as 9 November 2026.

| Status | Meaning |
| --- | --- |
| Active | Current instructions, design, specification or maintained guide |
| Planned | A delivery plan or work item whose execution remains pending |
| Completed | A finished work item or audit with recorded outcomes |
| Template | A reusable starting structure, not completed evidence |

Document status is separate from product implementation status. Active charters
can describe planned features. Label implemented, partial and planned capabilities
explicitly. Update the review date after a substantive review; do not change it
automatically without reviewing the content.

## Standard sections

Use the following H2 sections in order for each repeated document role. Additional
H3 sections may organize detail without creating a second requirements owner.

| Role | Required sections |
| --- | --- |
| README.md | Overview; Implementation status; Documentation; Requirements; Commands; Validation; Next milestone |
| AGENTS.md | Read first; Owned paths; Development rules; Verification; Handoff |
| Design.md and design template | Overview; Objectives; Functional requirements; Non-functional requirements; Back-of-the-envelope calculations; High-level design; Sequence diagram; Low-level design; Components and related details; Security and privacy; Observability; Metrics; Exception handling; Design considerations and trade-offs; Validation and acceptance gates |
| Project charter | Overview; Implementation status; Ownership and dependencies; Required V1 behavior; Public contracts; Correctness and failure boundaries; Acceptance matrix; Development checkpoints; Release gates; Deferred scope; References |

Use the [design template](design-template.md) for each maintained Design.md.
Objectives and functional requirements use tables with business and technical
distinctions; non-functional requirements use a table with bounds/targets, units,
verification and implementation/evidence status. Separate configured limits,
illustrative sizing, proposed experiment budgets and measured results. Show
inputs, formulas, results and exclusions in back-of-the-envelope calculations.

High-level design includes a Mermaid flowchart/graph and numbered explanation;
sequence uses sequenceDiagram; low-level uses classDiagram or stateDiagram-v2
with the actual/proposed components explained. Keep each closed nonempty diagram
inside its owning section. Preserve state ownership, interfaces, identity,
transaction/failure boundaries, implementation layout and lifecycle under H3s in
Components and related details. Add migration/restore, retention, security,
operational recovery, compatibility and ADR/open-question detail where relevant.
Data-only/tooling modules must explain their actual surface rather than invent a
runtime exporter or service. Logs, metrics and exceptions distinguish implemented
producers from planned ones. Every gate names sufficient evidence and missing
prerequisites. Link the shared Python and observability authorities.

The checker validates required design order/uniqueness, populated pipe tables
outside fenced/indented examples or HTML comments, and section-owned Mermaid
types/body presence. It is a structural Markdown subset, not a full renderer or
proof of the diagram's syntax/meaning. Parse Mermaid separately when diagrams
change and review the rendered relationships for authority/commitment accuracy.

Other shared guides use topic-specific sections with the same metadata and
writing rules. Keep obsolete implementation roadmaps out of starter/learning
guides. Link them to the build plan instead.

## Terminology and evidence

Use the three project names and P1/P2/P3 identifiers consistently. M1 refers only
to existing confirmed-investigation intake. V1 refers to the fixed project scope.
Use offline, lab and live for execution modes. The implemented shared lab uses
actual LiveKit with deterministic text and audio diagnostics and a browser
console. Record which native-client, container or browser path each check
exercised; native SDK reception does not establish browser playback. The default transport lab performs no speech recognition, reasoning or synthesis;
the G scripted profile uses declared fixtures rather than general inference. The
explicit local_real profile implements prepared local Whisper/Qwen/Piper inference,
whose actual engine/model/media qualification is tracked separately. The explicit
provider_real profile uses Deepgram/OpenAI/ElevenLabs with native-only private
keys. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. No current
profile implements P2/P3 specialist analysis. Working infrastructure does not complete any of the 54 product
scenarios (55 catalog definitions including the baseline). Use Local-ready V1 and Portfolio-ready V1 for product release gates.

Keep session, conversation, case, workflow, delegation, execution attempt, effect
and delivery identities distinct. Provider-account scope and verified business
account scope are different concepts. Case authority, execution, channel and
delegation ownership follow the root design.

Use exact assertions for deterministic behavior. Model judgments cannot replace
database/effect checks. Document actual observations, unknown outcomes and test
limits. Avoid subjective alignment scores, line-count targets, unconditional
latency promises and unsupported exactly-once claims.

## Commands, links and references

State the working directory and prerequisites for commands. Only verified
existing commands belong in runnable quickstarts. Clearly label future interfaces
and commands as planned. Document expected nonzero outcomes for incomplete gates.
Avoid hidden setup, implicit paid-service calls and destructive normal shutdowns.

Use relative local links within the repository. Link to public official
documentation, package metadata or versioned releases for external technical
claims. Keep prose free of internal project provenance, private repository links
and literal source-control identifiers. Use release-based source URLs. Code
snapshot identifiers and lock/image checksums can remain in machine run evidence
when reproducibility requires them.

All examples use synthetic data. Keep secrets, personal local paths and unrelated
business/project details out of ecosystem documentation. Retain accurate
assistance and authorship statements where they affect portfolio claims.

## Validation and maintenance

Run from the repository root. Prepare the frozen Python environment with the
all declared extras and development dependencies before the full fast lane; its implemented service tests
require those dependencies. The original intake-only test subset still uses the
standard library. The documentation checker itself is also dependency-free.

```sh
uv sync --frozen --all-extras --dev
.venv/bin/python -m harness.documentation_check
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh
```

Document Docker and browser validation separately from unit or structural checks.
A passing lab smoke establishes only its declared transport/readiness/intake
checks. Actual model quality and full product release require their own evidence.
Keep environment setup, safe lifecycle behavior and operational commands in the
local-setup guide rather than duplicating divergent instructions across projects.

The checker enforces corpus presence, titles, metadata, role section presence,
code fences, safe local links, prohibited reference forms and the structural
design rules above. Human review checks semantics, diagram meaning, scope,
authority, commands, quantitative assumptions and roadmap coherence.
Automated checks do not validate external website availability or establish
product behavior. Every new documentation rule needs positive and negative tests.
