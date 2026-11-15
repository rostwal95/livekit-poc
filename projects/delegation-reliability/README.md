# Delegation Reliability Kit

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Introduce P3: what is implemented, how the pieces fit, how to run and validate them and what remains planned |
| Audience | Engineers new to P3 or changing its packages; coding agents |
| Scope | The P3 project, its Python and TypeScript packages, examples and selected gates; per-API detail lives in the package guides |
| Owns | P3 product onboarding, slice status, repository commands and selected gate summaries |
| Related | [V1 charter](../../docs/projects/delegation-reliability-scope.md) · [Project design](Design.md) · [Project instructions](AGENTS.md) · [Python package guide](python/README.md) · [TypeScript specialist guide](specialist-ts/README.md) |

## Overview

The Delegation Reliability Kit (P3) builds a Python coordination software
development kit (SDK) and a TypeScript specialist service for reliable background
collaboration during a LiveKit conversation. The [V1 charter](../../docs/projects/delegation-reliability-scope.md)
defines behavior and the stable P3 acceptance IDs.

This guide is the project overview for engineers who are new to P3. It summarizes
what is implemented, how the pieces fit together, how to run and validate them and
what remains planned. Each package has its own guide, which also ships inside the
package and holds the API, configuration limits and lifecycle ownership:

| Component | Path | Responsibility | Documented in |
| --- | --- | --- | --- |
| `delegation-reliability` (import `delegation_reliability`) | [python/src/delegation_reliability](python/src/delegation_reliability) | Python coordination SDK | [Python package guide](python/README.md) |
| `@livekit-ecosystem/delegation-specialist` | [specialist-ts/src](specialist-ts/src) | TypeScript specialist service | [TypeScript specialist guide](specialist-ts/README.md) |
| Examples | [examples](examples) | Configured public Python examples | [Python package guide](python/README.md) |
| Project tests | [tests](tests) | Project test suites | [Commands](#commands) |
| Specialist tests | [specialist-ts/tests](specialist-ts/tests) | Specialist test suites and test-only fixtures | [TypeScript specialist guide](specialist-ts/README.md) |

Terms used throughout this guide:

| Term | Meaning |
| --- | --- |
| P1 | The agent-continuity project. It is the durable authority for accepted work, issued attempts, results, cases, delivery and guarded action. |
| P2 | The channel-continuity project. It provides the stable conversation receiver and the original channel input that origin-bound policy work retains. |
| ACK | Acknowledgement. |
| Issued attempt (grant) | A P1-created execution attempt. Only a newly issued, current and uncancelled running grant permits a specialist HTTP invocation. |
| `eligible_at_commit` | P1's time, lease and cancellation disposition for a stored result. It is not semantic validity or permission to act. |
| As-of applicability | A read-only, explicitly non-atomic observation of whether a result still fits current work and case state. |
| Possible send | A committed P1 delivery marker. It permits receiver lookup only, never a second acceptance. |
| Selected gate | A frozen set of named assertions that qualifies one slice. Passing it does not by itself register or complete a charter acceptance row. |

Contents:

- [Implementation status](#implementation-status): slice summary and the authority
  rules that apply to every slice
- [Documentation](#documentation), [Requirements](#requirements) and
  [Commands](#commands)
- [Capabilities](#capabilities): what each slice adds, with links to the package
  guides
- [Validation](#validation): what each gate exercises and its selected
  qualification
- [Next milestone](#next-milestone): remaining work

## Implementation status

P3 is partially implemented. P3-01, P3-03 and P3-11 have registered lab runners.
Fourteen complete product cases remain planned, so the full project gate remains
incomplete. Autonomous scheduling and real models remain planned. Actual PostgreSQL,
issued HTTP and process proof remain separate from fake-port checks.

### Slice summary

Each row links the handoff that records the slice's evidence. Status labels follow
the [implementation status vocabulary](../../docs/documentation-standards.md#implementation-status-vocabulary).
Gate commands and details are under [Validation](#validation).

| Slice | Capability | Status | Evidence |
| --- | --- | --- | --- |
| P3-A | Provider-free native baseline | Implemented | [0023](../../docs/work-items/0023-p3-native-baseline.md) |
| P3-I03/I04 | Strict cross-language first-capability contracts, local service principal and evidence checks, finite live-attempt boundary | Implemented | [0025](../../docs/work-items/0025-p3-specialist-contracts-and-trust.md): actual TypeScript producer tested through the installed Python consumer |
| P3-I05 | Authenticated loopback HTTP handler and client | Qualified | [0027](../../docs/work-items/0027-p2-standalone-and-p3-http.md): handler and client review and selected shared local gates passed |
| P3-I06 | Acceptance coordinator, managed-case adapter and Python HTTP consumer | Implemented | [0028](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P3-I07A | Issued execution runner | Qualified | [0029](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md): versioned upgrade, historical results and useful current-result gates recorded |
| P3-I07B | Result delivery and exact-confirmation action path | Qualified | [0030](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md): first explicit delivery and exact fake-action path qualified |
| P3-I08 | Concurrent admission proof, rejection inventory, public example | Qualified | [0031](../../docs/work-items/0031-revision-routing-and-delegation-acceptance.md): P3-01, P3-03 and P3-11 runners registered |
| P3-I09 | Result projection v1 | Qualified | [0032](../../docs/work-items/0032-linked-confirmation-and-result-projections.md): twelve actual PostgreSQL assertions |
| P3-I10 | Delivery-only processing v2 | Qualified | [0033](../../docs/work-items/0033-outbound-replies-and-completion-processing.md): sixteen actual assertions |
| P3-I11 | Applicability refresh and display retention v3 | Qualified | [0034](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md): 18-case actual fixture |
| P3-I12 | Validation of protected action and external-effect boundaries | Qualified | [0035](../../docs/work-items/0035-send-policy-and-action-races.md): sixteen selected assertions; measured source and installed qualification |
| P3-I13 | Deadline and cancellation schedules | Qualified | [0036](../../docs/work-items/0036-native-input-and-deadline-cancellation.md): eighteen selected temporal assertions |
| P3-I14 | Process-recovery qualification tooling | Qualified | [0037](../../docs/work-items/0037-playback-evidence-and-process-recovery.md): source and installed seventeen-assertion checks passed |
| P3-I15 | Standalone installed consumer | Qualified | [0038](../../docs/work-items/0038-case-rehydration-and-standalone-release.md): all sixteen selected assertions passed |
| P3-I16 | Read-only document (image) HTTP | Qualified | [0039](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md): twenty source and twenty installed assertions passed |
| P3-I17 | Fixed-policy version 2 HTTP | Qualified | [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md): twenty source and twenty installed assertions passed |
| P3-I18A | Durable fixed-policy version 2 | Qualified | [0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md): twelve source and twelve installed assertions passed |
| P3-I18B | Native background policy and compact real-time communication (RTC) text view | Qualified | [0042](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md): source and installed backend and browser gates passed |
| Result return | Fixed-policy result delivery | Qualified | [0043](../../docs/work-items/0043-stable-result-delivery-and-return-context.md): sixteen storage and four return assertions passed |
| Origin binding | Origin-bound channel policy | Qualified | [0044](../../docs/work-items/0044-origin-bound-channel-policy.md): unit and socket evidence; package lane and fourteen actual assertions passed; joined journey pending |

### Authority and safety boundaries

These rules apply across every slice. The package guides give the per-API detail.

- P1 is the only durable authority. It owns accepted work, issuance, results,
  delivery receipts, the case and guarded action. P3 adds no scheduler, execution
  ledger, queue or source acknowledgement.
- Specialists are read-only. The specialist receives no mutation permission, and
  image, policy and fact text is inert data that grants no tool or mutation
  permission.
- A result never authorizes an action or claims delivery by itself. Action requires a
  separately supplied exact confirmation, which P1's action port checks atomically
  with intent commitment.
- Receiver acceptance, carrier delivery, playback, human acknowledgement, supplier
  completion and guarded booking action are separate facts.
- Uncertainty is preserved. An existing possible send is lookup-only, and an
  ambiguous commit is reconciled by one exact read without another write.
- Read preflights and as-of applicability are observations, not atomic fences or
  action permission.
- Owned work keeps its capacity until actual settlement. Caller timeout or
  cancellation does not prove that remote work stopped, and close reports
  `cleanup_incomplete` while work is still held.
- Storage changes are explicit owner upgrades. Serving code performs no data
  definition language (DDL), that is, no schema changes.

## Documentation

| Document | Purpose |
| --- | --- |
| [Project instructions](AGENTS.md) | Agent workflow, development rules and verification for P3 |
| [Project design](Design.md) | P3 implementation boundaries and design decisions |
| [V1 scope and acceptance matrix](../../docs/projects/delegation-reliability-scope.md) | Project requirements and stable P3 acceptance IDs |
| [Granular implementation plan](../../docs/implementation/p3-delegation-reliability.md) | Phase gates, task prerequisites and failure evidence |
| [Python package guide](python/README.md) | Python API, configuration limits and lifecycle ownership |
| [TypeScript specialist guide](specialist-ts/README.md) | Specialist exports, HTTP routes, grants, resource bounds and fixtures |
| [Native baseline and isolation decision](../../docs/work-items/0023-p3-native-baseline.md) | Foundational work item for the provider-free baseline |
| [Contract and trust work item](../../docs/work-items/0025-p3-specialist-contracts-and-trust.md) | Foundational work item for contracts and local trust |
| [Shared architecture](../../Design.md) | Shared data flow, state authority, interfaces and failure boundaries |
| [Validation plan](../../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Technology baseline](../../docs/technology-baseline.md) | Selected versions and validation boundaries |
| [Harness guide](../../harness/README.md) | Harness commands and outcome semantics |
| [Local stack setup](../../local-setup/README.md) | Host requirements and lifecycle commands for the shared lab |
| [Local console](../../apps/local-console/README.md) | TypeScript operator console and browser lifecycle |

The granular plan's task IDs are not product acceptance IDs; the charter remains
authoritative. The 0023 and 0025 work items are foundational, and the
[slice summary](#slice-summary) links every later handoff.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python runtime | Pinned root Python runtime | Use it with the frozen `uv.lock` |
| Python dependencies | Frozen `uv.lock` with all declared extras and development dependencies | Install before running the full fast suite; service, Agents SDK and inference-boundary tests require them |
| Pure intake subset | Standard library only | Needs no third-party dependencies |
| External inference credentials | None | Not needed for the controlled baseline |
| Shared lab | Docker and Compose 2+ with pinned images | See the [local setup guide](../../local-setup/README.md) for host requirements and lifecycle commands |
| Selected versions | [Technology baseline](../../docs/technology-baseline.md) | Records selected versions and validation boundaries |
| Package runtimes | Per package | Listed in the [Python](python/README.md#requirements) and [TypeScript specialist](specialist-ts/README.md#requirements) guides |

## Commands

Run every command from the repository root. The table explains each task, and the
block below lists the commands for copying.

| Task | Command | Notes |
| --- | --- | --- |
| Install the frozen environment | `uv sync --frozen --all-extras --dev` | All declared extras and development dependencies |
| List P3 acceptance cases | `.venv/bin/python -m harness list --project p3` | Limits the harness list to P3 |
| Run the fast lane focused on P3 | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p3` | Still runs all current Python suites |
| Run the native baseline | `.venv/bin/python -m delegation_reliability` | Provider-free; prints one safe JSON report |
| Run the project tests | `.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v` | Unit and socket tests |
| Typecheck the specialist | `corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck` | Source and test projects |
| Test the specialist | `corepack pnpm --filter @livekit-ecosystem/delegation-specialist test` | Actual loopback sockets |
| Build the specialist | `corepack pnpm --filter @livekit-ecosystem/delegation-specialist build` | Compiles `src` to `dist` |
| Run the specialist demo | `make p3-demo` | Builds the specialist and runs its policy HTTP example |
| Run a selected slice gate | `make p3-execution-check` | Every `make p3-*` gate is listed under [Validation](#validation) |
| Run a registered lab runner | `.venv/bin/python -m harness run P3-01` | Use `P3-03` or `P3-11` for the other runners |
| Run the full project gate | `.venv/bin/python -m harness run --project p3` | Currently reports incomplete with exit 2 |

```sh
uv sync --frozen --all-extras --dev
.venv/bin/python -m harness list --project p3
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p3
.venv/bin/python -m delegation_reliability
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v
corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck
corepack pnpm --filter @livekit-ecosystem/delegation-specialist test
corepack pnpm --filter @livekit-ecosystem/delegation-specialist build
make p3-demo
make p3-execution-check
make p3-completion-check
make p3-projection-check
make p3-processing-check
make p3-applicability-check
make p3-action-races-check
make p3-deadlines-check
make p3-recovery-check
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
.venv/bin/python -m harness run --project p3
```

The final command currently reports incomplete with exit 2 because product
acceptance scenarios remain unimplemented. A passing structural check does not
complete those scenarios. The fast lane runs all current Python suites even when its
structural checks focus on this project.

The `make p3-*` gates and the other slice commands are described under
[Validation](#validation).

## Capabilities

Each subsection summarizes one slice or group of slices and links to the package
guide that holds its API, limits and ownership rules.

### Native baseline (P3-A)

The provider-free Python baseline compares one real native AgentSession tool with an
AgentTask inside the SDK TaskGroup, using the same immutable synthetic policy facts.
This is controlled same-process supervisor orchestration, not independent
background reasoning or product V1. The
[Python guide](python/README.md#native-baseline-p3-a) describes what it observes.

### Specialist contracts and loopback HTTP (P3-I03 to P3-I05)

P3-I03/I04 add strict Python and TypeScript first-capability contracts, local service
principal and evidence checks and a finite live-attempt boundary. The actual
TypeScript producer is tested through the installed Python consumer.

P3-I05 adds an authenticated loopback HTTP handler and client for one scripted
read-only policy capability. Status and cancellation are observations of live
attempts. They are not durable work or remote-stop guarantees. The
[TypeScript specialist guide](specialist-ts/README.md#http-routes-and-authority)
describes routes, grants and resource bounds.

### Coordinator and acceptance (P3-I06)

P3-I06 adds the Python submit, find, get and cancel coordinator through P1's public
opt-in read-only accepted-work profile, a read-only managed-case adapter and a typed
Python specialist HTTP consumer. P1 retains the original full canonical envelope
before acknowledgement. The coordinator is acceptance-only: P1 owns the only durable
acceptance record, and the coordinator starts no scheduler or specialist attempt.
See the [coordinator and case adapters](python/README.md#coordinator-and-case-adapters-p3-i06)
and the [specialist HTTP client](python/README.md#specialist-http-client).

### Issued execution (P3-I07A)

I07A adds an explicit one-step DelegationRunner over P1's owner-upgraded version-2
issued-execution profile. It invokes only a newly issued and freshly observed current
grant, validates scoped policy facts and retains a complete canonical result through
P1. Proposed wire attempts alone remain insufficient. Result eligibility at commit,
fresh read-only case applicability and action or delivery authority are separate.
See the [issued execution runner](python/README.md#issued-execution-runner-p3-i07a).

### Result delivery and exact action (P3-I07B)

I07B adds an explicit durable result delivery client, a cooperating persisted
receiver and an exact confirmation authorizer over P1's owner-upgraded v3 completion
profile. The actual v4 case authority atomically guards work and result eligibility
together with exact case intent. One existing leased P1 worker applies the fake
effect. See [result delivery](python/README.md#result-delivery-p3-i07b) and
[exact confirmation and guarded action](python/README.md#exact-confirmation-and-guarded-action-p3-i07b).

### Composition example and acceptance runners (P3-I08)

I08 adds actual concurrent admission and conflict proof, the complete bounded
rejection inventory and a public composition and inspection example.
[policy_completion.py](examples/policy_completion.py) composes explicit application
ports: two coordinators, one runner, a delivery facade and an authorizer. The
[Python guide](python/README.md#composition-and-inspection-example-p3-i08) describes
its use, and [registered acceptance runners](#registered-acceptance-runners)
describes the P3-03 and P3-11 runners.

### Result metadata (P3-I09 to P3-I11)

| Slice | Adds | Storage change | Configured example | Guide |
| --- | --- | --- | --- | --- |
| I09 | PostgreSQL projection over P1 work v4 result references, with explicit bounded steps and immutable as-of applicability | Owner-installed projection v1 | [result_projection.py](examples/result_projection.py) | [Result projection](python/README.md#result-projection-p3-i09) |
| I10 | Delivery-only processing, gap-aware discovery and immutable terminal event acknowledgements | Owner-upgraded v2 | [result_processing.py](examples/result_processing.py) | [Delivery-only processing](python/README.md#delivery-only-processing-p3-i10) |
| I11 | Explicit per-result as-of refresh commands, monotonic retained invalidation evidence and permanent display tombstones | Owner v3 upgrade | [result_applicability.py](examples/result_applicability.py) | [Applicability refresh](python/README.md#applicability-refresh-and-display-retention-p3-i11) |

P1 remains the source, result, case, delivery and action authority. The metadata
owns no queue, delivery or action ledger, or source acknowledgement.

### Failure schedules (P3-I12 to P3-I14)

These slices validate existing authorities rather than add runtime behavior.

- I12 validates the existing guarded action and external-effect boundaries under
  actual SQL revision and cancellation races and process loss. It adds no runtime
  API, schema or execution owner.
- I13 adds selected before- and during-invocation deadline and cancellation
  schedules over those same authorities, including a deliberately noncooperating
  test-only HTTP peer.
- I14 adds explicit specialist and coordinator process-recovery qualification
  tooling through the unchanged public authorities.

The schedules are described under [Validation](#validation). The resulting API
guarantees are in the
[Python guide](python/README.md#behavior-under-races-deadlines-and-process-loss).

### Package installation and standalone consumer (P3-I15)

I15 qualifies both packages as standalone installed consumers. The
[standalone package gate](#standalone-package-gate) builds fresh Python and npm
artifacts and runs strict consumers outside the checkout.
[standalone_policy.py](examples/standalone_policy.py) composes configured public
ports and calls `policy_completion.run_completion`; see the
[Python guide](python/README.md#standalone-composition-example-p3-i15).

### Document extraction (P3-I16)

I16 adds the read-only `booking.extract_document` capability beside the existing
policy wire. One scoped immutable PNG supplies four ordered fields: booking
reference, property, check-in and check-out. Missing and ambiguous values require
clarification. The finite scripted mapping is not optical character recognition
(OCR) or general vision inference.

Python exposes `DocumentSpecialistClient`; see the
[Python guide](python/README.md#document-extraction-client-p3-i16). TypeScript exposes
the document module, `DocumentHandler` and a configured scripted provider, and checks
the actual PNG bytes; see the
[TypeScript specialist guide](specialist-ts/README.md#document-capability-p3-i16).

P1's public work operation remains policy-only. Image HTTP is not durable image
acceptance, issued execution, projection, delivery, confirmation or action. A
reviewed versioned P1 operation extension is required before that integration.

### Fixed policy version 2 (P3-I17 and P3-I18A)

I17 implements an explicit input and result version 2 for `booking.evaluate_policy`.
Version-1 canonical bytes and public defaults stay unchanged. Version 2 accepts two
scoped immutable JSON sources: a `notice_v1` policy that declares only
`notice_minimum_days` with threshold seven, and zero to two identified notice-day
observations. A deterministic handler evaluates this one declared rule. Shape and
correlation validation are separate from factual verification, which also runs on
expired results.

The original DelegationCoordinator and DelegationRunner retain version-1 defaults.
I18A adds explicit FixedPolicyCoordinator and FixedPolicyRunner, which compose policy
version 2 through the same public P1 work and execution ports and shared typed
ownership cores. P1 accepts opaque policy-operation bytes; P3 verifies their
versioned facts. Projection, refresh and action remain version-1-only. Explicit
version-2 delivery is described in the next subsection.

See the Python [contract and client](python/README.md#fixed-policy-version-2-contract-and-client-p3-i17)
and [durable facades](python/README.md#durable-fixed-policy-p3-i18a), and the
TypeScript [handler and client](specialist-ts/README.md#fixed-policy-version-2-p3-i17).

### Fixed-policy result delivery

The explicit FixedPolicyDeliveryClient delivers verified v2 results through a stable
P2 conversation receiver. It looks up original receipts, preserves historical
context and denies stale delivery. See the
[Python guide](python/README.md#fixed-policy-result-delivery) and the
[0043 handoff](../../docs/work-items/0043-stable-result-delivery-and-return-context.md).

### Native background policy (P3-I18B)

NativePolicyApplication and NativePolicyAgent compose the explicit policy-v2 facades
with one supplied AgentSession. Trusted setup freezes one positive-revision request,
its original command and exactly two immutable JSON sources. The model receives no
scope, case, command or evidence-selection arguments. The first profile of the
configured [native_fixed_policy.py](examples/native_fixed_policy.py) example is
real-time communication (RTC) text with audio input and output disabled. See the
[Python guide](python/README.md#native-background-policy-p3-i18b).

### Origin-bound channel policy

The [0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md) adds
explicit ChannelPolicyCoordinator, ChannelPolicyRunner and
ChannelPolicyDeliveryClient facades. Their version-3 request and result envelopes
retain the original P2 profile, operation, input receipt, digest and byte length. The
specialist still consumes the unchanged policy-v2 contract.

Explicit accept returns the first accepted context across equal-origin retries. Exact
submit continues to compare the complete logical request, and a newly created
response must preserve every submitted byte. The application bridge and bounded
loopback publisher are implemented. This work adds no worker, provider call, new
queue, migration or complete charter registration. The
[Python guide](python/README.md#origin-bound-policy-version-3) describes the API and
the close order for applications.

## Validation

The [V1 acceptance matrix](../../docs/projects/delegation-reliability-scope.md)
defines the required scenarios. The [shared validation plan](../../docs/validation-plan.md)
separates deterministic correctness, actual local media and real-model evidence.
Local-ready V1 requires the designated local checks. Portfolio-ready V1 adds the
required real-model runs, review, benchmark evidence and demonstration.

Harness reports live under the ignored `.local/harness` directory. The shared local
stack has separate readiness and transport smoke checks and persistent volumes. Its
actual text and audio checks do not provide speech-to-text (STT), large language
model (LLM), text-to-speech (TTS) or product V1 evidence. Normal stop and start
preserves current local state. Use the documented explicit reset only when you
intend to remove synthetic data.

The gates below are selected slice checks, and each records its evidence in the
linked handoff. Apart from the three registered runners, they register no complete
charter row. Status labels follow the
[implementation status vocabulary](../../docs/documentation-standards.md#implementation-status-vocabulary).

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Issued execution (I07A) | `make p3-execution-check` | Versioned upgrade, historical results and useful current-result gates | Qualified |
| Completion (I07B) | `make p3-completion-check` | Thirteen named delivery and exact-action cases | Qualified |
| Registered runners (I08) | `.venv/bin/python -m harness run P3-01` | P3-01, P3-03 and P3-11 lab assertions; see [registered acceptance runners](#registered-acceptance-runners) | Qualified |
| Result projection (I09) | `make p3-projection-check` | Twelve actual PostgreSQL assertions | Qualified |
| Delivery-only processing (I10) | `make p3-processing-check` | Sixteen actual PostgreSQL and receiver assertions | Qualified |
| Applicability refresh (I11) | `make p3-applicability-check` | Bounded 18-case PostgreSQL and process fixture | Qualified |
| Action races (I12) | `make p3-action-races-check` | Sixteen selected assertions | Qualified |
| Deadlines and cancellation (I13) | `make p3-deadlines-check` | Eighteen selected temporal assertions | Qualified |
| Process recovery (I14) | `make p3-recovery-check` | Seventeen selected assertions with eight verified owned process kills | Qualified |
| Standalone package (I15) | `make p3-package-check` | Eight offline assertions; the lab run adds eight more | Qualified |
| Document HTTP (I16) | `.venv/bin/python local-setup/scripts/p3_document_check.py` | Twenty source image cases; installed mode repeats them | Qualified |
| Fixed-policy HTTP (I17) | `make p3-fixed-policy-check` | Twenty source assertions; the package check repeats them installed | Qualified |
| Durable fixed policy (I18A) | `make p3-fixed-work-check` | Twelve source assertions; the package check repeats them installed | Qualified |
| Native policy (I18B) | Recorded in the [native-policy handoff](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) | Twelve backend and SDK assertions and three browser groups | Qualified |
| Result return (0043) | Recorded in the [0043 handoff](../../docs/work-items/0043-stable-result-delivery-and-return-context.md) | Sixteen storage and four return assertions | Qualified |
| Origin-bound policy (0044) | `make channel-origin-unit`; other lanes in the [0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md) | Unit and socket evidence, package lane and fourteen actual assertions; joined journey pending | Qualified |
| Compatibility | Ten serial lanes recorded in the handoffs | 146 named assertions at the I16, I17 and I18A checkpoints | Qualified |
| Full project gate | `.venv/bin/python -m harness run --project p3` | Complete P3 product acceptance | Partial: fourteen product rows planned; exits 2 |

### Gate bounds

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Work horizon | At most 60 seconds per schedule | Action races (I12) | Unchanged; each schedule has its own |
| Gate budget | 180 seconds | Action races (I12) | Separate from the work horizon |
| Total time | 180 seconds | Deadlines (I13) | Reserves 15 seconds for cleanup |
| Processes | At most 24 | Deadlines (I13) | Started by the wrapper |
| Total time | 180 seconds | Process recovery (I14) | Includes 15 seconds for cleanup |
| Child processes | 28 planned | Process recovery (I14) | Within a ceiling of 32 |
| Total time | 120 seconds source; 360 seconds installed | Fixed-policy HTTP (I17) | Includes 20 seconds for cleanup |
| Owned child processes | At most 32 | Fixed-policy HTTP (I17) | None |
| Captured output | 64 KiB per stream; 2 MiB aggregate | Fixed-policy HTTP (I17) | None |
| Proof or report | 32 KiB each | Fixed-policy HTTP (I17) | None |
| Total time | 180 seconds source; 360 seconds installed | Durable fixed policy (I18A) | Includes 20 seconds for cleanup |
| Owned child processes | At most 32 | Durable fixed policy (I18A) | None |
| Captured output | 64 KiB per stream; 2 MiB aggregate | Durable fixed policy (I18A) | None |
| Proof or report | 32 KiB each | Durable fixed policy (I18A) | None |

### Execution and completion gates

`make p3-execution-check` (I07A) runs after the documented local restricted-role
PostgreSQL setup. It explicitly installs the v1 profile, seeds input, owner-upgrades
to v2 and uses actual TypeScript sockets. Only the case-read preflight is synthetic.
Owner credentials never enter runtime children. Package verification and complete
recovery, media, action and delivery acceptance remain separate gates. The
[I07A execution checkpoint](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
records the versioned upgrade, historical results and useful current-result gates.

`make p3-completion-check` (I07B) uses actual restricted-role PostgreSQL work v3 and
case v4, loopback TypeScript HTTP and the cooperating SQLite receiver. Owner and
runtime credentials are distinct, and owner credentials never enter runtime
children. Its thirteen named cases prove the following:

- stale result A at case revision 2 cannot deliver or act, while useful result B at
  revision 4 progresses;
- receiver commit ACK loss;
- changed route rejection;
- cancellation at the atomic guard;
- exact intent and one leased fake effect;
- later-cancel fact replay;
- fresh process reads; and
- receiver-commit SIGKILL reconciliation.

The trusted original inquiry supports a public-only ABA revision schedule, in which
the case moves away from the original request and back: original revision 2 becomes
stale after alternate revision 3 and original revision 4. No private quote injection
or revision offset is used. Exact confirmation remains a separate synthetic operator
input.

Independent SQL, receiver and supplier reads reconcile identities, exact
confirmation, result digests and counts. The Node completion fixture independently
counts four evaluations, holds stale A at an explicit barrier and observes zero
remaining resources. Synthetic evidence is retained under the ignored
`.local/validation/p3-completion` directory.
This is a bounded explicit path. It is not a recovering consumer, P2 route, voice,
real media or model, autonomous recovery or full charter qualification.

### Registered acceptance runners

P3-01, P3-03 and P3-11 have registered lab runners:

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| P3-01 | `.venv/bin/python -m harness run P3-01` | Thirteen lab assertions | Qualified |
| P3-03 | `.venv/bin/python -m harness run P3-03` | Eight lab assertions, including concurrent acceptance | Qualified |
| P3-11 | `.venv/bin/python -m harness run P3-11` | Twelve lab assertions for rejection bounds | Qualified |

P3-I08's actual P3-03 runner proves concurrent acceptance:

- It starts three separate runtime processes after their initial scoped reads
  missed. Original acceptance holds P1's admission lock, and the owner independently
  observes one SQL holder and two blocked backends before release.
- Equal input returns the same logical work, and changed nested content conflicts.
  Caller mutation cannot change the original canonical bytes, and fresh reads from
  another tenant or account disclose nothing.
- One selected issued HTTP invocation still returns useful policy evidence.

This proves one logical acceptance, without promising one physical computation under
arbitrary retry.

The P3-11 runner covers every malformed-output, wrong-revision, unsupported-schema,
mismatched-tenant and context, image or result size negative:

- Both language codecs and evidence registries reject safely before decoding images.
- Five named invalid HTTP outputs pass through actual P1-issued runner attempts. None
  commits a result, and a later valid result progresses.
- Fixed public reasons preserve the difference between schema or factual errors and
  the runner's `transport_unknown` observation.

These checks qualify rejection bounds, not image extraction or model quality.

### Result metadata gates

`make p3-projection-check` (I09) proves twelve actual PostgreSQL assertions,
separate from unit fake-port evidence. They cover two owned-process commit-boundary
kills, fresh resume, original replay under observed SQL contention, as-of
preservation across case-only revisions, scoped, source and capacity rejection and
independently reconciled zero intents and effects. These selected I09 gates do not
register P3-04 or P3-08 or qualify autonomous recovery.

`make p3-processing-check` (I10) provides sixteen actual PostgreSQL and receiver
assertions. They include five owned-process kills, a concurrent projector snapshot
schedule, immutable receipts, independent identity reconciliation and independent
cleanup. No scheduler, provider call, automatic action or full P3 release is added.
The [phase handoff](../../docs/work-items/0033-outbound-replies-and-completion-processing.md)
records the selected evidence, qualification limits and remaining boundaries. Full
P3-04 and P3-08 remain unregistered.

`make p3-applicability-check` (I11) exercises the bounded 18-case PostgreSQL and
process fixture. It includes five owned process kills, SQL contention, a populated
profile-row restore and a separately confirmed fake B action. This fixture is
distinct from new HTTP, media or provider evidence. The
[phase handoff](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
records the exact observed qualification and limitations, the source-bound gate
results, the populated quiescent profile-row restore and the isolated installed
consumer. No full P3-05 registration, automatic accept or action retry, or
source-incarnation repair is added.

### Protected action and external-effect schedules

`make p3-action-races-check` (I12) exercises sixteen selected assertions through
unchanged public P1 work, case and action clients and P3 completion facades. Its
tooling schedules existing public action failpoints and leased worker hooks in fresh
synthetic authorities. No new P3 or P1 runtime module, API or schema is required.

Revision races, where A is the pending action and B a competing case revision:

- A passes the facade preflight before two prewarmed writers queue behind an
  isolated case admission lock. Actual `pg_blocking_pids` chains prove both writer
  orders within P1's unchanged lock timeout.
- B first: B commits the first revision change before stale A is rejected. A later
  trusted ABA edit produces current B4 with its own exact confirmation and one useful
  supplier application. This does not imply that both ABA edits preceded A's
  protected check.
- A first: A commits its intent, rejects B's revision with `intent_committed` and
  preserves the original A receipt and successful effect.

Cancellation and process loss:

- Separate freshly quoted suppliers prove that cancellation before intent or
  dispatch prevents application. After-claim cancellation leaves a safe
  `TransitionConflict`, and cancellation after reservation cannot fence an admitted
  external call.
- A process killed after independent supplier success is recovered by exact lookup
  without another physical apply, after cancellation and observed work and lease
  expiry.
- Three owned process kills cover the cuts before and after action commit and at
  supplier commit.
- Original cancellation commands keep their original disposition. A fresh terminal
  command observes `already_terminal`.
- Caller abandonment retains actual I/O capacity, and close remains incomplete until
  settlement.

Each schedule has a fresh quote and supplier. Its work horizon and the separate gate
budget are listed under [gate bounds](#gate-bounds). The gate preserves caller I/O
after timeout or cancellation, original command receipts, finite role-separated
resources and exact independent identity reconciliation.
Independent SQL and SQLite reads join exact scope, work, attempt, request and result
digests, confirmation, intent and effect, supplier truth and receiver identities.
Result receiver acceptance, supplier or business completion and human
acknowledgement remain separate. The unchanged
[configured public example](examples/policy_completion.py) performs read-only
inspection; only separate exact controller input authorizes an action.

The [phase handoff](../../docs/work-items/0035-send-policy-and-action-races.md)
records measured source and isolated installed-consumer qualification and remaining
scope. No P1 or P3 runtime or schema change, automatic retry or acceptance
registration follows.

### Deadline and cancellation schedules

`make p3-deadlines-check` (I13) composes the existing public P1 and P3 clients with
eighteen selected temporal assertions, covering before- and during-invocation
schedules.

- P1 samples its own database clock after admission. Producer timestamps never
  restore eligibility.
- Expiry or cancellation before a new invocation creates no new HTTP evaluation.
- A held invocation may still return a strict late result, which remains an
  immutable, ineligible fact in P1.
- Result recording, refreshed applicability, remote cancel ACK and exact action
  permission remain separate observations.

The test-only `deadline-peer.mjs` intentionally ignores business cancellation and
expiry; see the
[TypeScript specialist guide](specialist-ts/README.md#fault-and-recovery-fixtures).
The production `SpecialistServer` remains cooperative and unchanged.

- A running cancel ACK does not establish remote stop, and a lost cancel ACK stays
  unknown.
- Waiter timeout or cancellation retains the actual HTTP and runner slot and does
  not itself request business cancellation.
- A previously eligible result remains eligible at its original commit after its
  grant lease expires. Later work cancellation is observed separately.
- Current separately confirmed work still delivers and applies one fake effect, with
  exact physical supplier, receiver and source identity reconciliation.

The wrapper's time, cleanup and process bounds are listed under
[gate bounds](#gate-bounds). It retains three closed proof files with directly
reviewable IDs, digests, timing observations and one actual SQL blocking graph.
These direct proof sidecars independently bind source, work, attempt and body
digests, the receiver receipt and actual supplier calls. One owned kill follows a
late result commit, and fresh inspection looks up that original fact without another
invocation.

This selected proof adds no recovering scheduling or remote cancellation guarantee.
The [phase handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records qualification and failure provenance separately from offline fake-port
checks.

### Explicit process recovery

`make p3-recovery-check` (I14) runs the explicit actual PostgreSQL and process
fixture: seventeen selected assertions with eight verified owned process kills and
one prewarmed two-waiter SQL graph.

- The coordinator can lose its process after persisted issuance before the first
  HTTP call, during actual HTTP, or around result, delivery, receiver and
  guarded-action commits.
- Fresh processes inspect original accepted bytes, exact owner and command grants,
  results and receipts.
- Only a newly created explicit command, after P1 observes that the old lease
  expired, may invoke again. Replaying the original command never invokes, and
  changing its owner conflicts. These rules do not promise one physical read-only
  computation.

The five early recovery works use a clearly labelled synthetic read-only case
preflight. Completion work has a separate authenticated account and an actual P1
case, quote and independently supplied exact confirmation. An unknown possible
delivery (work G) remains lookup-only and unACKed, while current work M obtains its
own receiver receipt, processing ACK and guarded intent. One existing leased worker
applies one fake supplier effect, and later cancellation preserves the original
delivery and action receipts. The configured public example inspects these facts
without authorizing another action.

Three bounded proofs retain all authority, peer and SQL identities. They directly
join source, request and result, Python and SQL backend, receiver and supplier
identities. Captured writer process and backend process IDs are compared with the
parent's owned process handles, and the observer never adopts unrelated role-wide
waiters. A killed server retains its last running observation, and only a normally
closed server reports zero actual occupancy. Time and child-process bounds are
listed under [gate bounds](#gate-bounds). Diagnostics are bounded and body-free, and
diagnostic mode never qualifies.

The [phase handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records the observed qualification and failure provenance. The source and isolated
installed seventeen-assertion recovery checks passed there, recorded separately from
offline tests. This validation adds no scheduler, source ACK, automatic accept
retry, inferred consent, P1 or P3 runtime API or storage schema. P3-04 and P3-08
registration remains separately gated.

### Standalone package gate

The maintained `make p3-package-check` command (I15) builds a fresh declared P1
dependency wheel, the P3 wheel, source archive and rebuilt wheel, and the specialist
npm archive. It checks exact payloads, raw package guides, wheel RECORD and
dependencies, installed public imports and strict consumers. It then executes the
native baseline and the shipped HTTP example outside the checkout. The default eight
assertions need cached frozen build dependencies and no database, room or provider
configuration.

For the explicitly configured local lab, run:

```sh
.venv/bin/python local-setup/scripts/p3_package_check.py --lab --report .local/validation/p3-package/<fresh-name>.json
```

The lab run repeats the eight offline assertions and adds eight lab assertions; the
sixteen total are not sixteen PostgreSQL scenarios. The lab uses actual P1 work and
case authority, the installed scripted HTTP specialist, a cooperating SQLite receiver
and one leased synthetic supplier effect.

1. A caller process is killed after known completion.
2. A fresh process replays the original owner, request and commands. Lookup reads
   are allowed, while new issue, completion or authorization writes, specialist
   invocation, receiver acceptance and supplier apply must remain zero.
3. Cancellation preserves the original result, delivery and action receipts and the
   terminal ACK. A separate refresh records invalidation without new permission.

Three bounded proofs join exact identities, and a complete retained-file index binds
nested summaries and captures. This is local synthetic qualification, not P2
integration, remote models, human acknowledgement or a full charter release. The
selected host is macOS arm64 with Python 3.14.10 and Node 24.22.2. Other platforms
and a published release remain separate qualification work.

The selected I15 gate passed all sixteen assertions, comprising eight offline and
eight installed lab assertions, with one owned caller-process kill and complete
cleanup. Fresh Python archives preserved all thirty runtime payloads, the npm archive
preserved sixteen, and the declared P1 wheel preserved seventy-seven. The
[current handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records the source-bound evidence, failure provenance and remaining work.

### Document HTTP gate

Inspect the closed twenty-case inventory with:

```sh
.venv/bin/python local-setup/scripts/p3_document_check.py --plan
```

| Task | Command | Notes |
| --- | --- | --- |
| Inspect the closed twenty-case inventory | `.venv/bin/python local-setup/scripts/p3_document_check.py --plan` | The command shown above |
| Run the source gate | `.venv/bin/python local-setup/scripts/p3_document_check.py` | The same script without flags; actual local Python and Node HTTP |
| Run the installed gate | `.venv/bin/python local-setup/scripts/p3_document_check.py --installed` | Rebuilds fresh artifacts, repeats the maintained offline package assertions and reruns the same twenty image cases outside the checkout |

These are socket, contract and fixture checks, not twenty PostgreSQL or real-model
scenarios. The selected host remains Python 3.14.10 and Node 24.22.2 on macOS
arm64.

Selected I16 qualification passed twenty source assertions and the same twenty
installed assertions. Installed mode also passed the separate eight offline package
assertions. Both image runs observed eight scripted provider entries, seventeen
worker records and five canonical client-returned wires, with complete cleanup. The
I16 checkpoint's fresh archives preserved thirty-two Python and twenty-seven npm
payloads and the declared P1 dependency's seventy-seven payloads. The
[image handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records the selected qualification, retained failures and remaining gates.

### Fixed-policy HTTP gate

| Task | Command | Notes |
| --- | --- | --- |
| Inspect the twenty-case inventory | `make p3-fixed-policy-plan` | None |
| Run the source contract and loopback journey | `make p3-fixed-policy-check` | Twenty source assertions |
| Run the same journey using fresh installed artifacts | `make p3-fixed-policy-package-check` | Also repeats eight offline package assertions |

Installed mode separately repeats eight offline package assertions; twenty is not a
PostgreSQL or model-inference count. The declared budgets and capture limits are
listed under [gate bounds](#gate-bounds). The selected host is macOS arm64, Python
3.14.10 and Node 24.22.2.

Selected I17 qualification passed twenty source assertions and the same twenty from
fresh installed artifacts; installed mode separately passed eight offline package
assertions. The
[fixed-policy handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records source, installed and affected compatibility results and retained failure
provenance.

### Durable fixed-policy gate

| Task | Command | Notes |
| --- | --- | --- |
| Inspect the declared twelve-assertion journey | `make p3-fixed-work-plan` | None |
| Run the source journey | `make p3-fixed-work-check` | Twelve source assertions |
| Run the installed journey | `make p3-fixed-work-package-check` | Also repeats eight offline package assertions |

Installed mode separately repeats eight offline package assertions. The selected
bounds are listed under [gate bounds](#gate-bounds).

The synthetic local profile creates thirteen issued attempts, retains eight valid
results and rejects five invalid bodies. It includes one owned postcommit kill,
fresh-process original lookup and independent scoped authority proofs.

Selected I18A qualification passed twelve source assertions and twelve isolated
installed assertions, with eight separate offline package assertions. Each durable
journey exercised thirteen invocations, retained eight validated results and
rejected five invalid bodies. The
[I18A handoff](../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records the measured outcomes, prerequisites and retained failure provenance.

### Native policy gate

Selected I18B native RTC text qualification passed twelve backend and SDK
assertions and three browser groups in both source and isolated installed modes,
with eight separate installed package assertions and complete cleanup. The
[native-policy handoff](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records its commands, exact bounds, first-failure provenance and the compact UI.
Full charter and release acceptance is separate.

### Result-return gate

For fixed-policy result delivery (0043), selected sixteen storage and four return
assertions passed with original-receipt lookup, historical context and
stale-delivery denial. The source result-return gate used three real P1 results, two
P2 receipts and no carrier or provider calls. Its specialist port is explicitly
scripted, and native-grant reads use no RTC room, so these are scripted and
public-port checks without a room or provider. The separate fresh package gate
checks installed public ports and twenty unchanged fake-port tests. It requires its
own passing report; source execution does not substitute for an installed consumer.
Joined voice, text and SMS qualification and fresh installed qualification remain
separate; see the
[0043 handoff](../../docs/work-items/0043-stable-result-delivery-and-return-context.md).

### Origin-bound gate

For origin-bound policy (0044), the application bridge and bounded loopback
publisher have unit and socket evidence. Run `make channel-origin-unit` from the repository
root. The isolated origin package lane passed its eight offline assertions and 20
legacy plus 41 origin fake-port tests. Fourteen real P2/P1 original-input
assertions passed with complete cleanup. Installed actual repetition remains
separate later evidence, and the joined native, voice and SMS journey remains
pending. The [0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md)
records these checks.

### Compatibility gate

The affected compatibility gate runs ten serial lanes. At the I16 checkpoint, its 146
named assertions included the sixteen-assertion policy composition gate and the
registered P3-01, P3-03 and P3-11 counts of thirteen, eight and twelve. The total
includes the policy gate's eight offline assertions, so it is not a
PostgreSQL-only count.

| Checkpoint | Compatibility result | Affected regression gates |
| --- | --- | --- |
| I16 | Passed 146 named assertions | None recorded here |
| I17 | The full affected compatibility run passed 146 assertions again | The current document gates passed twenty source and twenty installed assertions, with another separate offline eight |
| I18A | The fresh ten-lane compatibility batch passed 146 assertions with complete cleanup | The affected fixed-policy and document source and installed gates passed twenty assertions each |

## Next milestone

The [slice summary](#slice-summary) shows what has passed its selected gates. The
[granular implementation plan](../../docs/implementation/p3-delegation-reliability.md)
sequences the remaining tasks. Remaining work:

| Step | Outcome | Gate |
| --- | --- | --- |
| Complete the fourteen planned P3 product rows | Complete P3 product acceptance | Full project gate, which remains incomplete |
| Register P3-04 and P3-08, and fully register P3-05 | Registered rows; no full P3-05 registration exists yet | P3-04 and P3-08 registration is separately gated |
| Qualify broader platforms and a published release | Other platforms and a published release qualified | Separate platform, release and integrated comparison gates |
| Run the joined native, voice and SMS journey for origin-bound policy | Origin-bound policy in the joined journey | Joined journey gate, which remains pending |
| Qualify joined voice, text and SMS for result return | Result return in the joined journey | Separate joined qualification |
| Add autonomous scheduling and real models | Scheduling and real-model evidence | Planned; Portfolio-ready V1 requires real-model runs |
