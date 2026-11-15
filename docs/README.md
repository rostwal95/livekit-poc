# Documentation map

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | List every maintained document, grouped by audience and purpose, so readers can find the document that owns a topic |
| Audience | Newcomers, contributors, reviewers and coding agents looking for a document |
| Scope | Every maintained document plus the demo videos, license notices and acceptance catalog; excludes generated artifacts and ignored local state |
| Owns | Documentation map for every maintained document |
| Related | [Root README](../README.md) · [Documentation standards](documentation-standards.md) · [Root AGENTS.md](../AGENTS.md) · [Contributing](../CONTRIBUTING.md) |

This map lists the maintained documents in this repository, grouped by audience
and purpose. Use it to find the document that owns a topic. Every link is
relative to this `docs` directory.

The map has seven groups:

| Group | Contents |
| --- | --- |
| [Start here](#start-here) | Orientation for newcomers and contributors |
| [Architecture and design](#architecture-and-design) | Shared design, guides and decisions |
| [Projects](#projects) | P1, P2 and P3 charters, guides and packages |
| [Services and applications](#services-and-applications) | Runnable services, the browser console and shared contracts |
| [Operations](#operations) | The local stack, inference profiles and gates |
| [Planning and validation](#planning-and-validation) | Scope, plans, standards and the harness |
| [History](#history) | Work items, checkpoints and audits |

## Start here

| Document | Purpose |
| --- | --- |
| [Root README](../README.md) | Landing page: demo video, the three projects, architecture, quickstart and current status |
| [Ecosystem demo video](media/ecosystem-demo.mp4) | Two-minute recording of the joined showcase and one P1 business case |
| [Showcase-only clip](media/channel-policy-demo.mp4) | Earlier 80-second recording of the joined showcase |
| [Investigation intake starter walkthrough](project-brief.md) | Run and read the original M1 confirmed-investigation intake on SQLite |
| [Learning plan](learning-plan.md) | Learning objectives and exercises aligned with the build plan stages |
| [Contributing](../CONTRIBUTING.md) | Contributor workflow, quality bar, usability feedback and handoff checks |
| [Root AGENTS.md](../AGENTS.md) | Coding-agent reading order, owned paths, development rules and verification |

## Architecture and design

| Document | Purpose |
| --- | --- |
| [Root Design.md](../Design.md) | Shared data flow, state authority, interfaces and failure boundaries for P1, P2 and P3 |
| [Exact consent and durable continuation](case-and-continuation.md) | P1 case authority, exact quote confirmation, durable waits, signals and retry/deadline policy (Phase D) |
| [Exact effects and durable completion](effects-and-completion.md) | P1 supplier mutation, reconciliation, cancellation and completion delivery (Phase E) |
| [Leases and local worker operations](leases-and-workers.md) | P1 lease epochs, conditional worker writes, bounded admission and the local worker process (Phase F) |
| [Conversation and durable-work showcase](conversation-and-showcase.md) | Native AgentSession over P1 durable work and the browser case workspace (Phase G) |
| [Observability and failure handling](observability.md) | Current and planned signals, safe errors, cardinality and operational evidence |

### Architecture decisions

Each decision records a reviewed architecture choice and its rationale.

| Decision | Title |
| --- | --- |
| [0001](decisions/0001-runtime-boundaries.md) | Runtime, package and persistence boundaries |
| [0002](decisions/0002-sqlite-inquiry-subset.md) | Explicit SQLite inquiry execution and migration |
| [0003](decisions/0003-postgres-cutover-and-scope.md) | Controlled PostgreSQL cutover and restricted runtime |
| [0004](decisions/0004-case-authority-and-continuation.md) | Case authority and persisted continuation |
| [0005](decisions/0005-effects-cancellation-and-outbox.md) | Supplier effects, cancellation and completion delivery |
| [0006](decisions/0006-database-leases-and-bounded-worker.md) | Database leases and bounded worker execution |
| [0007](decisions/0007-native-conversation-and-local-media.md) | Native conversation, local media and exact approval |

## Projects

Each project has a charter that defines its V1 behavior and stable acceptance
IDs, a README for onboarding, a Design.md for its architecture and an AGENTS.md
for coding-agent rules.

### P1 Agent Continuity

| Document | Purpose |
| --- | --- |
| [Agent Continuity Lab scope](projects/agent-continuity-scope.md) | P1 charter: required V1 behavior and stable P1 acceptance IDs |
| [Agent Continuity Lab README](../projects/agent-continuity/README.md) | Project overview, implementation status and working commands |
| [Agent Continuity Lab design](../projects/agent-continuity/Design.md) | Component design of the durable business-work boundary |
| [Agent Continuity Python distribution](../projects/agent-continuity/python/README.md) | Installable `agent-continuity` package (`continuity_lab`), its public API and installed commands |
| [P1 AGENTS.md](../projects/agent-continuity/AGENTS.md) | Coding-agent rules for P1 |

### P2 Channel Continuity

| Document | Purpose |
| --- | --- |
| [Channel Continuity Kit scope](projects/channel-continuity-scope.md) | P2 charter: required V1 behavior and stable P2 acceptance IDs |
| [Channel Continuity Kit README](../projects/channel-continuity/README.md) | TypeScript SDK and gateway overview, status and commands |
| [Channel Continuity Kit design](../projects/channel-continuity/Design.md) | Design, boundaries, limits and failure rules of every implemented slice |
| [Channel Continuity Python adapter](../projects/channel-continuity/python/README.md) | Python `channel-continuity` codec and optional native LiveKit adapters |
| [Source-qualified communication contract](../projects/channel-continuity/COMMUNICATION.md) | Topic guide: opt-in I17 communication profile (inbox schema version 7) |
| [Current-case rehydration contract](../projects/channel-continuity/REHYDRATION.md) | Topic guide: opt-in I18 read-only current-case profile |
| [Bounded channel workload profile](../projects/channel-continuity/WORKLOAD.md) | Topic guide: opt-in I19 workload study |
| [Channel operations](../projects/channel-continuity/OPERATIONS.md) | Topic guide: opt-in I20 read-only operations profile and operator page |
| [Installed channel starter](../projects/channel-continuity/STARTER.md) | Topic guide: I21 installed starter application |
| [P2 AGENTS.md](../projects/channel-continuity/AGENTS.md) | Coding-agent rules for P2 |

### P3 Delegation Reliability

| Document | Purpose |
| --- | --- |
| [Delegation Reliability Kit scope](projects/delegation-reliability-scope.md) | P3 charter: required V1 behavior and stable P3 acceptance IDs |
| [Delegation Reliability Kit README](../projects/delegation-reliability/README.md) | Project overview for engineers new to P3 |
| [Delegation Reliability Kit design](../projects/delegation-reliability/Design.md) | Coordination library and specialist service design, limits and qualification |
| [Delegation Reliability Python package](../projects/delegation-reliability/python/README.md) | Python `delegation-reliability` coordinator, issued-result runner and facades |
| [Delegation specialist contracts and local HTTP](../projects/delegation-reliability/specialist-ts/README.md) | TypeScript specialist contracts and authenticated loopback HTTP boundary |
| [P3 AGENTS.md](../projects/delegation-reliability/AGENTS.md) | Coding-agent rules for P3 |

## Services and applications

For each component, the README explains how to run and use it, Design.md
explains how it is built and AGENTS.md holds its coding-agent rules.

| Component | Purpose | Documents |
| --- | --- | --- |
| Joined channel-policy application | Opt-in Python application that joins P1, P2 and P3 for the joined showcase | [README](../services/channel_policy_demo/README.md), [Design](../services/channel_policy_demo/Design.md), [AGENTS](../services/channel_policy_demo/AGENTS.md) |
| Channel policy gateway | Node side of the joined application: native/SMS intake, source reads and result receipts | [README](../services/channel-policy-gateway/README.md), [Design](../services/channel-policy-gateway/Design.md), [AGENTS](../services/channel-policy-gateway/AGENTS.md) |
| Local control API | Authenticated local HTTP for M1 intake, business work, current-case reads and media grants | [README](../services/control_api/README.md), [Design](../services/control_api/Design.md), [AGENTS](../services/control_api/AGENTS.md) |
| Native conversation agent | LiveKit Agents consumer of P1 durable work with scripted, local_real and provider_real profiles | [README](../services/conversation_agent/README.md), [Design](../services/conversation_agent/Design.md), [AGENTS](../services/conversation_agent/AGENTS.md) |
| Local transport diagnostic agent | Worker that verifies LiveKit text and audio transport without model inference | [README](../services/rtc_agent/README.md), [Design](../services/rtc_agent/Design.md), [AGENTS](../services/rtc_agent/AGENTS.md) |
| Local continuity console | Browser console: the P1 business console plus the P2, P3 and joined showcase pages | [README](../apps/local-console/README.md), [Design](../apps/local-console/Design.md), [AGENTS](../apps/local-console/AGENTS.md) |
| Shared contracts | Small language-neutral fixtures that producers and consumers test against | [README](../contracts/README.md), [Design](../contracts/Design.md), [AGENTS](../contracts/AGENTS.md) |
| UI asset notices | Licenses and provenance of the console's vendored fonts and LiveKit symbol | [ASSET-NOTICES](../apps/local-console/public/vendor/livekit/ASSET-NOTICES.md) |

## Operations

| Document | Purpose |
| --- | --- |
| [Local setup guide](../local-setup/README.md) | Operations manual for the isolated Docker stack: setup, lifecycle, profiles, gates, reset and troubleshooting |
| [Local setup design](../local-setup/Design.md) | Design of the orchestration boundary: state, credentials, failure containment and gates |
| [Local setup AGENTS.md](../local-setup/AGENTS.md) | Coding-agent rules for local-setup |
| [Provider inference demo operations](provider-demo.md) | Opt-in provider_real setup, private keys, declared pipeline and provider qualification |
| [Local real-inference operations](local-real-inference.md) | Opt-in local_real Whisper, Qwen and Piper profile, its resources and qualification limits |
| [Qualification gates and optional profiles](qualification-gates.md) | Opt-in qualification commands, optional profiles and registered acceptance runners |
| [Local speech engine notices](../local-setup/inference/NOTICES.md) | Licenses for the local Whisper and Piper engines |

## Planning and validation

| Document | Purpose |
| --- | --- |
| [Portfolio scope](portfolio-scope.md) | V1 boundaries, execution modes and release definitions shared by the three projects |
| [Build plan](build-plan.md) | Authoritative PLAN-01 to PLAN-22 work-package sequence, dependencies and estimates |
| [Granular implementation roadmap](implementation-plan.md) | Task decomposition and cross-project execution gates under the build plan |
| [P1 implementation plan](implementation/p1-agent-continuity.md) | P1 tasks for the durable business-work library |
| [P2 implementation plan](implementation/p2-channel-continuity.md) | P2 package, gateway, Python adapter and browser example tasks (PLAN-12 to PLAN-16) |
| [P3 implementation plan](implementation/p3-delegation-reliability.md) | P3 coordination library and capability service tasks |
| [Validation plan](validation-plan.md) | Test lanes, required fault scenarios, benchmarks and release evidence |
| [Technology baseline](technology-baseline.md) | Version policy, compatibility, exact pins and promotion rules |
| [Demo plan](demo-plan.md) | Capability demonstrations and honest observable UI transitions |
| [Python engineering](python-engineering.md) | Python API, typing, async/resource, persistence and diagnostics practices |
| [Documentation standards](documentation-standards.md) | Corpus, authority, metadata, required sections, terminology and link rules |
| [Design template](design-template.md) | Standard structure for every Design.md |
| [Harness README](../harness/README.md) | Harness commands: discover requirements, check contracts and run implemented tests |
| [Harness design](../harness/Design.md) | Structural and behavioral planes of the harness |
| [Harness architecture](harness-architecture.md) | Harness components, module ownership and acceptance evidence |
| [Harness AGENTS.md](../harness/AGENTS.md) | Coding-agent rules for the harness and scripts |
| [Acceptance catalog](../harness/catalog.json) | Machine-readable executable acceptance registrations |

## History

| Document | Purpose |
| --- | --- |
| [Work item template](work-items/template.md) | Template for new implementation work items |
| [Checkpoint history](checkpoint-history.md) | Per-slice qualification summaries, newest first |
| [Plan audit](plan-audit.md) | Whole-ecosystem plan, structure and harness audit: findings, corrections and remaining limits |
| [Documentation audit](documentation-audit.md) | Earlier documentation-only audit and its corrections |

### Work items

Work items are the change plans, verification records and handoffs.

| Items | Coverage |
| --- | --- |
| 0007 to 0019 | P1 phases A to H |
| 0022 to 0044 | The P2 and P3 slices |
| 0045 to 0047 | Building the joined showcase |
| 0048 | The whole-repository code audit and documentation cleanup |

| Work item | Title |
| --- | --- |
| [0001](work-items/0001-portfolio-foundation.md) | Portfolio scope and harness foundation |
| [0002](work-items/0002-documentation-audit.md) | Documentation audit and ecosystem build plan |
| [0003](work-items/0003-local-project-foundation.md) | Standalone repository and local transport foundation |
| [0004](work-items/0004-plan-and-showcase-audit.md) | Plan audit and observable capability showcase |
| [0005](work-items/0005-granular-implementation-plan.md) | Granular phasewise implementation planning |
| [0006](work-items/0006-design-and-engineering-gates.md) | Standardized designs and engineering acceptance gates |
| [0007](work-items/0007-p1-phase-a-execution-foundation.md) | P1 Phase A schema-safe execution foundation |
| [0008](work-items/0008-p1-phase-b-inquiry-recovery.md) | P1 Phase B independent inquiry and crash reconciliation |
| [0009](work-items/0009-p1-phase-c-postgres-cutover.md) | P1 Phase C PostgreSQL cutover and scoped access |
| [0010](work-items/0010-p1-phase-d-authority-and-waits.md) | P1 Phase D exact consent and durable continuation |
| [0011](work-items/0011-p1-phase-e-effects-and-completion.md) | P1 Phase E supplier effects and durable completion |
| [0012](work-items/0012-p1-phase-f-leases-and-deployment.md) | P1 Phase F leases and bounded worker deployment |
| [0013](work-items/0013-p1-phase-g-conversation-and-showcase.md) | P1 Phase G conversation, visible continuity and traces |
| [0014](work-items/0014-p1-phase-h-workload-baseline.md) | P1 Phase H1 declared inquiry workload baseline |
| [0015](work-items/0015-p1-reliability-workloads.md) | P1 Phase H2 restart and slow-supplier workloads |
| [0016](work-items/0016-p1-standalone-package.md) | P1 Phase H3 standalone package and public API |
| [0017](work-items/0017-p1-local-real-inference.md) | P1 Phase H4 local speech and model inference |
| [0018](work-items/0018-p1-provider-demo.md) | P1 hosted-provider qualification |
| [0019](work-items/0019-p1-phase-h-release-qualification.md) | P1 Phase H release qualification |
| [0020](work-items/0020-architecture-audit-reconciliation.md) | Architecture audit reconciliation and plan updates |
| [0021](work-items/0021-p1-operational-safety-extensions.md) | P1 operational safety extensions |
| [0022](work-items/0022-p2-channel-contracts.md) | P2 versioned channel contract slice |
| [0023](work-items/0023-p3-native-baseline.md) | P3 controlled native baseline and remote-isolation decision |
| [0024](work-items/0024-p2-verified-durable-intake.md) | P2 verified provider boundary and durable intake |
| [0025](work-items/0025-p3-specialist-contracts-and-trust.md) | P3 specialist contracts and local trust boundary |
| [0026](work-items/0026-p2-postgres-inbox.md) | P2 PostgreSQL association and durable inbox |
| [0027](work-items/0027-p2-standalone-and-p3-http.md) | P2 standalone intake and P3 specialist HTTP boundary |
| [0028](work-items/0028-p2-dispatch-and-p3-coordinator.md) | Recoverable P2 dispatch and P3 durable submission |
| [0029](work-items/0029-p2-gateway-and-p3-issued-execution.md) | Gateway recovery and issued specialist execution |
| [0030](work-items/0030-p2-agent-recovery-and-p3-completion.md) | Agent recovery and delivered guarded results |
| [0031](work-items/0031-revision-routing-and-delegation-acceptance.md) | Revision routing and delegation acceptance |
| [0032](work-items/0032-linked-confirmation-and-result-projections.md) | Linked confirmation and resumable result projections |
| [0033](work-items/0033-outbound-replies-and-completion-processing.md) | Outbound replies and resumable completion processing |
| [0034](work-items/0034-callback-evidence-and-applicability-refresh.md) | Correlated callback evidence and refreshed result applicability |
| [0035](work-items/0035-send-policy-and-action-races.md) | Explicit send uncertainty policy and protected action races |
| [0036](work-items/0036-native-input-and-deadline-cancellation.md) | Native committed input and delegation deadline cancellation |
| [0037](work-items/0037-playback-evidence-and-process-recovery.md) | Source-qualified playback evidence and process recovery |
| [0038](work-items/0038-case-rehydration-and-standalone-release.md) | Case rehydration and standalone release |
| [0039](work-items/0039-bounded-channel-workloads-and-image-evidence.md) | Bounded channel workloads and image evidence |
| [0040](work-items/0040-operations-ui-and-fixed-policy-evidence.md) | Operations UI and fixed-policy evidence |
| [0041](work-items/0041-standalone-channel-and-durable-policy.md) | Standalone channel application and durable fixed-policy prerequisite |
| [0042](work-items/0042-responsive-native-policy-and-compact-demo.md) | Responsive native policy conversation and compact demo |
| [0043](work-items/0043-stable-result-delivery-and-return-context.md) | Stable result delivery and current-channel return context |
| [0044](work-items/0044-origin-bound-channel-policy.md) | Origin-bound channel policy acceptance |
| [0045](work-items/0045-joined-native-channel-policy.md) | Joined native channel and background policy application |
| [0046](work-items/0046-joined-showcase-providers-and-demo.md) | Joined showcase providers, hardening and demo |
| [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) | Open review findings, schema upgrades and landing page |
| [0048](work-items/0048-code-audit-fixes-and-documentation-cleanup.md) | Code audit fixes and documentation cleanup |
