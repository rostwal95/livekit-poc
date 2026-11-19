# Delegation specialist contracts and local HTTP

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain the specialist contracts, authenticated local HTTP boundary and supported consumer commands |
| Audience | Engineers using or changing the TypeScript specialist package |
| Scope | Read-only policy/document capabilities and local fixtures; excludes durable execution authority |
| Owns | TypeScript specialist onboarding, exports, requirements and validation limits |
| Related | [Project guide](../README.md) · [Project design](../Design.md) · [Coding instructions](../AGENTS.md) · [Python guide](../python/README.md) |

## Overview

`@livekit-ecosystem/delegation-specialist` is a TypeScript contract and
authenticated loopback HTTP boundary for the read-only `booking.evaluate_policy`
capability and the standalone `booking.extract_document` capability. It uses Node
built-ins, explicit scripted providers and configured evidence. Importing the
package starts no service and reads no credentials. P1, the agent-continuity
authority, remains the sole durable acceptance, issued-execution and result owner
through its separately installed public profiles.

This guide ships inside the npm package. It covers the public exports, server and
client usage, HTTP routes and grants, resource bounds and the test fixtures. The
Python coordinator, runner and completion facades that call this service are
described in the [Python package guide](../python/README.md). Repository gates and
qualification results are in the [project guide](../README.md#validation).

Contents:

- [Implementation status](#implementation-status)
- [Documentation](#documentation), [Requirements](#requirements) and
  [Commands](#commands), including installed-package use
- [Public API](#public-api): exports, server and client, document and fixed-policy
  capabilities
- [Validation](#validation): routes and authority, resource bounds, tests and
  fault fixtures
- [Next milestone](#next-milestone)

## Implementation status

This package implements the following slices:

| Slice | Adds |
| --- | --- |
| P3-I03/I04 | Strict request, result and error codecs, local bearer-digest grants, scoped immutable evidence and finite live-attempt permits |
| P3-I05 | The bounded HTTP handler and typed client, with focused actual-socket verification |
| P3-I16 | A separate typed document handler; see [document capability](#document-capability-p3-i16) |
| P3-I17 | The fixed-policy version 2 handler and client; see [fixed-policy version 2](#fixed-policy-version-2-p3-i17) |
| P3-I18A | Verified historical observation; see [observed fixed-policy results](#observed-fixed-policy-results-p3-i18a) |

The bounded handler and client review and the selected shared local gates passed.
Their exact evidence belongs to the linked handoffs; the
[HTTP/standalone handoff](../../../docs/work-items/0027-p2-standalone-and-p3-http.md)
records the P3-I05 shared review and release gates.

### How Python slices use this package

- **Acceptance and issued execution.** The Python I06 coordinator owns immutable
  acceptance through P1's public work port. I07A's one-step runner calls this HTTP
  boundary under P1-issued grants, records strict results through P1's
  owner-upgraded v2 execution port and keeps durable result history with P1. The HTTP
  service authenticates its own local service principal and does not independently
  verify P1 issuance in this wire version. Its ephemeral state never becomes a
  ledger or action authority.
- **Delivery and exact action.** Python I07B composes durable delivery and exact
  action through public P1 v3 ports, without granting this specialist mutation
  permission.
- **Registered runners.** P3-I08 qualifies the registered P3-01, P3-03 and P3-11 lab
  runners. It runs all codec and evidence bounds in both languages and five named
  invalid HTTP output variants under actual issued Python runner attempts, followed
  by useful progress.
- **Result metadata.** Python I09 projects P1 work v4 result references into a
  separate versioned as-of metadata store. This changes no TypeScript wire contract
  or service ownership, and result bytes remain authoritative in P1. Python I10 adds
  explicit v2 processing metadata and terminal delivery acknowledgements with
  gap-aware scan progress. Python I11 adds explicit refreshed applicability and
  display tombstones in its own versioned metadata profile. These changes add no
  TypeScript scheduler, send or action authority, wire change, new specialist
  permission or remote-stop guarantee. The
  [phase handoff](../../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
  records the exact selected qualification.
- **Action races.** Python I12 composes the existing public P1/P3 guarded-action path
  under real revision and cancellation lock orders and process loss. The specialist
  remains a read-only producer with no action, revision, retry or supplier
  permission. The
  [action-race handoff](../../../docs/work-items/0035-send-policy-and-action-races.md)
  records that selected validation separately from this unchanged TypeScript wire.
- **Native application.** The explicit I18B native Python application uses this
  unchanged public HTTP capability; see the
  [Python guide](../python/README.md#native-background-policy-p3-i18b). The
  [native-policy handoff](../../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
  records implementation and selected qualification.

Autonomous recovery, real models, media and complete P3 acceptance rows remain
outside this HTTP slice. Fourteen P3 rows remain planned.

## Documentation

| Document | Use |
| --- | --- |
| [Project guide](../README.md) | Project scope and entry points |
| [Python package guide](../python/README.md) | Coordinator and durable integration |
| [Project design](../Design.md) | Ownership and failure boundaries |
| [Project coding instructions](../AGENTS.md) | Change and validation rules |
| [Contract and trust checkpoint](../../../docs/work-items/0025-p3-specialist-contracts-and-trust.md) | Contract/trust evidence |
| [HTTP/standalone handoff](../../../docs/work-items/0027-p2-standalone-and-p3-http.md) | HTTP and standalone qualification |
| [Issued execution checkpoint](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md) | Issuance integration evidence |
| [Shared version-one fixtures](../../../contracts/delegation/v1.json) | Language-neutral contract examples |

## Requirements

| Requirement | Detail |
| --- | --- |
| Node tooling | Frozen root pnpm environment, Node 24.22.2 or 26.13.0, pinned TypeScript and Vitest |
| Contract parity | Installed Python 3.14 workspace |
| HTTP tests | Actual owned loopback sockets; no Docker, provider, model download or paid credential |
| Runtime inputs | Token digests and source bytes from trusted configuration; the example uses synthetic facts and a newly generated local token |

## Commands

From the repository root after frozen dependency installation:

| Command suffix | Purpose |
| --- | --- |
| `typecheck` | Check the declared TypeScript surfaces |
| `test` | Run the package tests with their stated local prerequisites |
| `build` | Produce the package artifacts |
| `demo` | Build and run the owned local policy HTTP example |

```sh
corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck
corepack pnpm --filter @livekit-ecosystem/delegation-specialist test
corepack pnpm --filter @livekit-ecosystem/delegation-specialist build
corepack pnpm --filter @livekit-ecosystem/delegation-specialist demo
```

The demo builds the package and runs [`examples/policy-http.mjs`](examples/policy-http.mjs).
It starts one ephemeral server, calls it through the actual typed client, prints a
safe candidate summary and closes owned resources. It performs no business mutation,
durable submission or real-model reasoning.

### Installed package

The package installs from its packed npm archive, which contains `package.json`,
`dist`, `examples` and this guide. In a consumer project, the shipped HTTP example
runs as:

```sh
node node_modules/@livekit-ecosystem/delegation-specialist/examples/policy-http.mjs
```

The repository's `make p3-package-check` builds this archive together with the
Python artifacts. It checks exact payloads, the raw package guide and installed
public imports, then runs this shipped example outside the checkout. Its assertions
and outcomes are in the [project guide](../README.md#standalone-package-gate), and
the [standalone handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records exact outcomes and remaining work.

## Public API

### Package exports

| Import path | Provides |
| --- | --- |
| `@livekit-ecosystem/delegation-specialist` | Contracts and codecs, `LocalTrust`, `EvidenceRegistry`, `AttemptBoundary`, `SpecialistServer`, `SpecialistClient` and the document module |
| `@livekit-ecosystem/delegation-specialist/http` | `SpecialistServer`, `SpecialistClient` and the HTTP types |
| `@livekit-ecosystem/delegation-specialist/document` | `DocumentHandler`, the configured scripted provider and the document codecs and client |
| `@livekit-ecosystem/delegation-specialist/fixed-policy` | `FixedPolicyRequest`/`FixedPolicyResult`, their strict codecs, `FixedPolicyHandler`, `FixedPolicySpecialistClient` and `verifyFixedPolicyFacts` |

The package also ships three configured examples: `examples/policy-http.mjs`,
`examples/document-http.mjs` and `examples/fixed-policy.mjs`.

### Server and client

1. Construct `SpecialistServer` with `LocalTrust` and `EvidenceRegistry`.
2. Call its `listen` method. It binds only `127.0.0.1` on an ephemeral port and
   returns the endpoint.
3. Construct `SpecialistClient` with that endpoint and a trusted Bearer header.
   `invoke` returns a `DelegationResult`; `status` and `cancel` return an
   `AttemptObservation`.
4. Close both through `try`/`finally`.

The client accepts a literal loopback endpoint, never an arbitrary URL, and performs
no redirects or retries. Route grants and resource bounds are under
[Validation](#validation).

### Document capability (P3-I16)

I16 adds the read-only `booking.extract_document` capability beside the existing
policy wire. This package exposes the public document module, `DocumentHandler` and
a configured scripted provider. Python exposes `DocumentSpecialistClient` and
separate document request and result codecs. The configured
[`examples/document-http.mjs`](examples/document-http.mjs) accepts explicit clients
and requests. Importing loads no source image, model, listener or credentials; the
application owns the configured evidence and clients.

#### Fields and verification

- One scoped immutable PNG supplies four ordered fields: booking reference,
  property, check-in and check-out.
- Known values carry exact source and region witnesses. Missing and ambiguous values
  require clarification.
- Structural validity and exact correlation are checked separately from the
  independent synthetic-image factual oracle.
- Image text remains inert data. The finite scripted mapping is not optical
  character recognition (OCR) or general vision inference, and no mutation or
  notification permission comes from its output.

#### PNG checks, worker and ownership

Actual PNG bytes are checked before provider entry:

| Check | Limit |
| --- | --- |
| Size | At most 2 MiB |
| Dimensions | At most 2048×2048 |
| Pixel format | RGB8 or RGBA8, noninterlaced |
| Structure | Bounded framing, cyclic redundancy check (CRC), zlib, scanline and filter checks |

Unsupported formats, animation or ancillary chunks, truncation and trailing data
fail closed.

- The fixed worker runs without an inherited environment or caller-selected code.
  Normal results require an actual exit code 0.
- Direct handler calls, workers, sockets and provider promises retain finite
  ownership through timeout or cancellation and incomplete shutdown.
- A fresh original deadline is checked after decoding, before provider work.
- Retrying public close observes remaining owners rather than assuming remote
  cancellation.

P1's public work operation remains policy-only. Image HTTP is not durable image
acceptance, issued execution, projection, delivery, confirmation or action. A
reviewed versioned P1 operation extension is required before that integration. Full
charter and release qualification remains separate. The
[image handoff](../../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records qualification, provenance and remaining gates, and the
[project guide](../README.md#document-http-gate) describes the repository gate.

### Fixed-policy version 2 (P3-I17)

I17 implements an explicit input and result version 2 for `booking.evaluate_policy`.
Version-1 canonical bytes and public defaults stay unchanged.

The public `@livekit-ecosystem/delegation-specialist/fixed-policy` export provides
`FixedPolicyRequest`/`FixedPolicyResult`, their strict codecs, `FixedPolicyHandler`,
`FixedPolicySpecialistClient` and `verifyFixedPolicyFacts`. Pass an explicit handler
to `SpecialistServer` to enable version 2; an unconfigured server preserves the
version-1 default. [`examples/fixed-policy.mjs`](examples/fixed-policy.mjs) accepts
configured request, client and evidence ports and runs the separate factual check.

#### Version-2 rule and evidence

The typed path accepts two scoped immutable JSON sources:

- a `notice_v1` policy that declares only `notice_minimum_days`, with threshold
  seven; and
- zero to two identified notice-day observations.

Source reference versions remain independent of the semantic policy version. All
exact source bytes, digests, scope and complete fact witnesses must match.

| Observations | Outcome |
| --- | --- |
| Two agreeing observations | Usable |
| Missing or conflicting observations | Clarification required |
| Invented rules or values | Factual verification fails |

Policy, fact and image text remains data and grants no tool or mutation permission.

#### Verification and client behavior

Shape and correlation validation and factual verification are separate. Factual
checks also run on expired results, so lateness cannot hide unsupported answers. The
fixed handler is a deterministic evaluator of this one declared rule, without a
model, provider call, generic policy interpreter or new worker.

The configured public examples receive explicit requests, evidence and clients, and
importing them performs no setup. Client metrics describe owned transport calls and
validated correlations, not factual truth or business permission. Timeout or
cancellation retains actual I/O until settlement, and incomplete close and later
close retry remain explicit.

The original Python `DelegationCoordinator` and `DelegationRunner` retain version-1
defaults. The explicit Python `FixedPolicyCoordinator` and `FixedPolicyRunner`
compose version 2 through the same public P1 work and execution ports; see the
[Python guide](../python/README.md#durable-fixed-policy-p3-i18a). P1 accepts opaque
policy-operation bytes, and P3 verifies their versioned facts. Projection, refresh
and action remain version-1-only. The
[fixed-policy handoff](../../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records source, installed and affected compatibility results and retained failure
provenance.

### Observed fixed-policy results (P3-I18A)

`FixedPolicySpecialistClient.invokeObserved(request, records)` copies and validates
that exact pair of evidence records before I/O, then verifies every fact and witness,
even on a late result. It returns the typed result, the observation time and a
separate candidate, clarification or expired classification. The existing `invoke`
method remains the correlation-only transport API. Python offers the same check as
`invoke_observed(request, evidence=records)`.

The `observeFixedPolicy` export of
[`examples/fixed-policy.mjs`](examples/fixed-policy.mjs) receives explicit public
clients, evidence and identities. It performs no implicit DDL (schema change),
provider setup or scheduling.

The durable Python `FixedPolicyCoordinator` and `FixedPolicyRunner` use this
capability, and only a newly issued current P1 grant permits their HTTP invocation.
See the [Python guide](../python/README.md#durable-fixed-policy-p3-i18a) for the
facades and the [project guide](../README.md#durable-fixed-policy-gate) for the
repository gate.

## Validation

### HTTP routes and authority

| Route | Required grants | Observation |
| --- | --- | --- |
| POST /v1/invoke | invoke and result for the capability, plus each evidence source | One synchronous scripted result; combined result access is checked before work starts |
| POST /v1/status | result for the exact active attempt | Ephemeral running observation with separate deadline, disconnect, cancel and closing flags |
| POST /v1/cancel | cancel for the exact active attempt | Request observed; an HTTP 202 response does not prove computation stopped |

Every route uses the existing exact `DelegationRequest` envelope. The body cannot
grant its own scope or permissions.

- Status and cancel never return source bytes, fabricate durable acceptance or
  retain terminal history. After actual work settles and the original permit is
  released, a later status returns `unknown_attempt`.
- A concurrent same-attempt invocation conflicts. A released attempt has no durable
  deduplication record here; the P1 owner must decide any subsequent attempt or
  reconciliation.
- The server computes against authorized source bytes and checks
  `verifyPolicyFacts`.
- `verifyPolicyFacts` checks factual support before it classifies a result as
  expired or clarification, in the same order as Python. An expired result with
  an unsupported eligibility answer therefore fails with `unsupported_facts`.
- The client independently checks strict response shape, identity, current attempt,
  deadline and evidence-reference binding. It cannot independently establish
  factual truth without separately supplied source bytes.
- A source-grounded candidate still needs current-case applicability and exact
  consent at the case authority.

### Resource and lifetime bounds

| Resource | Default ceiling |
| --- | --- |
| TCP connections / concurrent HTTP readers and handlers | 16 / 16; raw incomplete headers count as connections |
| Live evaluations / each principal | 4 / 2; no waiting queue |
| Headers | 8 KiB and 16 raw fields; duplicates and unsupported framing rejected |
| Input / result / observation / error | 16 KiB / 8 KiB / 1 KiB / 512 bytes |
| Headers / body / invoke / response / shutdown | 1 s / 2 s / 5 s / 1 s / 2 s |
| Typed client | 4 active sockets, 5 s total request budget, no retries |
| Observer promises | At most 8 unsettled notifications; excess notifications counted and dropped |

Trusted configuration may lower server limits.

- Each connection serves one request. Keepalive cannot create another dispatch, and
  pipelining is rejected.
- Owned timers explicitly end sockets and requests. Monotonic checks also reject a
  late body, evaluation or client success when a timeout callback is delayed.
- The remaining business deadline is checked against trusted time, not a result's
  reported completion timestamp.

Cancellation, expiry and disconnect request an `AbortSignal`. An uncooperative
trusted harness barrier retains the original permit until it actually settles.
Bounded shutdown then reports `cleanup_incomplete` and can be attempted again after
settlement; it cannot advertise successful cleanup or start replacement work. The
optional `beforeEvaluate` hook is a trusted harness-only barrier, never a public
executor or something request JSON can select.

The default observer emits finite structured fields and no input, source bytes or
credentials. Synchronous exceptions and asynchronous rejections are contained, and
actual failures and drops appear in numeric metrics. Observer adapters own any
external resources they create. No custom exporter or production-capacity claim is
added.

### Tests

Tests use actual loopback requests for useful result, status and cancel
progression, operation grants, deadlines, aborts, raw header, framing and body
bounds, socket and request saturation, pipelining, malformed and late responses,
cleanup and safe observation. Contract tests preserve exact cross-language canonical
bytes and separate schema validity, source identity and factual checks. Missing or
skipped required checks cannot qualify the slice.

### Fault and recovery fixtures

The following test-only fixtures live under `tests/fixtures`.

#### Noncooperating deadline peer (I13)

`tests/fixtures/deadline-peer.mjs` is an intentionally noncooperating I13 fault
peer, separate from the production `SpecialistServer`. It uses the public
specialist package and finite scope, evidence and attempt checks, while allowing a
held read-only computation to finish after business cancellation or expiry.

- Its running cancel acknowledgement (ACK) is non-durable, and one cancel endpoint
  deliberately loses that ACK.
- Actual result readiness is recorded separately from the producer's claimed
  completion.
- Caller timeout or cancellation retains the actual HTTP task, so the original
  response may still be recorded. Socket closure is not manufactured from waiter
  abandonment.
- Closed counters distinguish cumulative computations from live requests, sockets
  and attempts, and are inspected again after actual owned shutdown.

The Python gate proves that P1 authority rejects late applicability and action and
preserves useful current work. No remote retry, queue or mutation permission is
introduced. The
[I13 handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records selected qualification and limitations.

#### Recovery server (I14)

`tests/fixtures/recovery-server.mjs` composes the unchanged public
`SpecialistServer` and evidence registry. It adds no durable acceptance, retry,
queue or new permission.

- Generation A is killed while an actual read-only call is active. Generation B
  observes a real coordinator socket loss through a cooperative `AbortSignal`, then
  serves useful later calls.
- Only a public `attempt_started` event counts an invocation, since successful
  source resolution can still precede a capacity rejection.
- Public completion and abort observations are separate from the P1 result and
  receipt history.
- The bounded journal retains exact scope, wire-attempt and request identities and
  real public counters. It refreshes changed metrics after settlement, before
  replacement work.
- A killed process keeps its last running snapshot and cannot advertise graceful
  zero occupancy. The normally closed process reports actual zero requests, sockets
  and active attempts only after close.
- No request body selects a hook, module, process, account or process ID (PID).

The Python `make p3-recovery-check` orchestration retains the source and receipt
truth through P1 public ports; its assertions are described in the
[project guide](../README.md#explicit-process-recovery). The
[phase handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records source and installed qualification separately; this fixture alone is not
that gate. No remote durable-status or exactly-once physical computation claim
follows.

#### Acceptance and completion fixtures

- The acceptance-server fixture intentionally hosts an invalid test peer alongside
  the actual public specialist server for the P3-I08 invalid-output runs. Request
  JSON selects no test hook.
- The separate Python `make p3-completion-check` qualifies the first I07B delivery
  and exact case-authorized fake-action path using this actual service. Its
  completion fixture independently counts four evaluations, holds stale result A at
  an explicit barrier and observes resource cleanup. It adds no public handler state
  or permissions.

## Next milestone

The I16 bounded standalone image path has selected source and installed
qualification. I17 fixed-policy HTTP remains independently usable. I18A adds
explicit durable policy-v2 Python facades and verified historical observation in
both languages; the
[I18A handoff](../../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records its implementation and selected qualification.

| Remaining work | Boundary |
| --- | --- |
| Broader real-model and modality qualification | Separate from the selected I18B RTC-text gate recorded in [0042](../../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) |
| Autonomous recovery, real models, media and complete P3 acceptance | Outside this HTTP slice |
| Fourteen full charter rows and broader integrated release | Planned |
