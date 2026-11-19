# Delegation Reliability Python package

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe the package's public API, defaults and limits, what each facade owns and closes and what it does not guarantee |
| Audience | Developers who compose the package into an application; coding agents |
| Scope | The installed `delegation-reliability` distribution; repository gate commands, assertion counts and qualification results live in the project guide |
| Owns | Python public API, facade defaults and limits, and facade lifecycle ownership |
| Related | [Project guide](../README.md) · [Project design](../Design.md) · [P3 charter](../../../docs/projects/delegation-reliability-scope.md) · [TypeScript specialist guide](../specialist-ts/README.md) |

## Overview

The `delegation-reliability` distribution (import name `delegation_reliability`)
provides a typed Python coordinator, an issued-result runner, explicit delivery and
confirmation composition, and bounded projection, processing and applicability
clients over public P1 authority. Later slices add document, fixed-policy, native
and origin-bound facades. A controlled comparison on the native LiveKit Agents
software development kit (SDK) remains available as a separate provider-free
baseline.

This guide ships inside the package. It is for developers who compose the package
into an application. It describes the public API, defaults and limits, what each
facade owns and closes, and what each facade does not guarantee. Repository gate
commands, assertion counts and qualification results live in the
[project guide](../README.md#validation).

Terms used in this guide:

| Term | Meaning |
| --- | --- |
| P1 | The agent-continuity package (`continuity_lab`, distribution `agent-continuity`). It is the durable authority for accepted work, issued attempts, results, cases, delivery and guarded action. |
| P2 | The channel-continuity project. It provides the stable conversation receiver and the original channel input. |
| ACK | Acknowledgement. |
| CAS | Compare-and-set: a write that succeeds only while the stored revision still matches the expected one. |
| DDL | Data definition language, that is, schema changes. Serving code performs none; only explicit owner setup changes schemas. |
| Issued attempt (grant) | A P1-created execution attempt. Only a newly issued, current and uncancelled running grant permits an HTTP invocation. |
| Possible send | A committed P1 delivery marker. It permits receiver lookup only, never a second acceptance. |
| As-of applicability | A read-only, explicitly non-atomic observation of whether a result still fits current work and case state. It never grants permission. |
| `cleanup_incomplete` | The close outcome while owned work has not yet settled. Retry close after actual settlement. |

### Version namespaces

Version numbers below belong to separate contracts. An upgrade in one namespace
does not upgrade the others.

| Namespace | Versions or selector | Meaning |
| --- | --- | --- |
| P1 work profile | v1 to v4 | Acceptance; issued execution/results; delivery/action; result feed, respectively |
| P3 input and result | v1, v2, v3 | Original policy context; separate policy/fact sources; channel-origin wrapper around v2 |
| P3 derived metadata | v1 to v3 | Projection; processing/terminal ACKs; applicability refresh/display retention, respectively |
| HTTP envelope and routes | `schema_version=1`, `/v1/*` | Transport compatibility; independent of the input/result version |
| P1 booking schema | See the [P1 guide](../../agent-continuity/README.md) | Case, effect and lease storage; independent of the opt-in work profile |

The origin-bound runner unwraps its v3 input for the existing v2 specialist. A
metadata-v3 profile does not make projection or guarded action support policy-v3
payloads; the explicit facade determines the supported payload contract.

Contents:

- [Implementation status](#implementation-status), including the native baseline
- [Documentation](#documentation), [Requirements](#requirements) and [Commands](#commands)
- [Acceptance, execution and completion](#acceptance-execution-and-completion):
  coordinator, specialist client, runner, delivery, guarded action and examples
- [Result metadata](#result-metadata): projection, processing, refresh and display
  retention
- [Behavior under races, deadlines and process loss](#behavior-under-races-deadlines-and-process-loss)
- [Document and fixed-policy capabilities](#document-and-fixed-policy-capabilities)
- [Native and channel-origin policy](#native-and-channel-origin-policy)
- [Validation](#validation) and [Next milestone](#next-milestone)

## Implementation status

The table lists what each slice adds to this package and the handoff that records
its evidence. Status labels follow the
[implementation status vocabulary](../../../docs/documentation-standards.md#implementation-status-vocabulary)
and match the project guide's [slice summary](../README.md#slice-summary). Fourteen
complete P3 product cases remain planned.

| Slice | Capability | Status | Evidence |
| --- | --- | --- | --- |
| P3-A | Focused native baseline, described below | Implemented | [0023](../../../docs/work-items/0023-p3-native-baseline.md) |
| P3-I03/I04 | `contracts` and `security` modules: strict policy wire, local principal and evidence checks, and finite ephemeral permits | Implemented | [0025](../../../docs/work-items/0025-p3-specialist-contracts-and-trust.md) |
| P3-I05 | Nothing in Python: the TypeScript package implements the scripted HTTP specialist | Not applicable | [0027](../../../docs/work-items/0027-p2-standalone-and-p3-http.md) |
| P3-I06 | `SpecialistClient` and the `DelegationCoordinator` submit/find/get/cancel API through P1's public opt-in read-only accepted-work profile | Implemented | [0028](../../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P3-I07A | `DelegationRunner` through P1's separately owner-upgraded version-2 public `ExecutionPort` | Qualified | [0029](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| P3-I07B | Explicit result delivery and exact-confirmation authorization through public P1 v3 ports, with an exact case-control read and a cooperating persisted local receiver | Qualified | [0030](../../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P3-I08 | Public composition and inspection example, plus registered lab runners for P3-01, P3-03 and P3-11 | Qualified | [0031](../../../docs/work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P3-I09 | Explicit result projection | Qualified | [0032](../../../docs/work-items/0032-linked-confirmation-and-result-projections.md) |
| P3-I10 | Delivery-only processing | Qualified | [0033](../../../docs/work-items/0033-outbound-replies-and-completion-processing.md) |
| P3-I11 | Applicability refresh and display retention | Qualified | [0034](../../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md) |
| P3-I12 | Validation of selected protected action, revision and cancellation races through existing authorities | Qualified | [0035](../../../docs/work-items/0035-send-policy-and-action-races.md) |
| P3-I13 | Selected deadline and cancellation schedules, without runtime changes | Qualified | [0036](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md) |
| P3-I14 | Process recovery composition | Qualified | [0037](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md): selected source and installed qualification |
| P3-I15 | Standalone composition | Qualified | [0038](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md): selected source and installed qualification |
| P3-I16 | Separate read-only document (image) HTTP client | Qualified | [0039](../../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| P3-I17 | Versioned fixed-policy HTTP contract and client | Qualified | [0040](../../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| P3-I18A | Durable fixed-policy version 2 facades | Qualified | [0041](../../../docs/work-items/0041-standalone-channel-and-durable-policy.md) |
| P3-I18B | Native background policy application and configured text example | Qualified | [0042](../../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md): their own evidence scope |
| Result return | Fixed-policy result delivery | Qualified | [0043](../../../docs/work-items/0043-stable-result-delivery-and-return-context.md) |
| Origin binding | Origin-bound policy version 3 | Qualified | [0044](../../../docs/work-items/0044-origin-bound-channel-policy.md): installed actual repetition and joined journey remain separate |

### Native baseline (P3-A)

The provider-free baseline compares one real native `AgentSession` tool with an
`AgentTask` inside the SDK `TaskGroup`. Both receive the same immutable synthetic
policy facts, answer a useful read-only question while held and expose the eventual
result through the SDK. This is controlled same-process supervisor orchestration,
not independent background reasoning or product V1. [Commands](#commands) shows how
to run it, and [Validation](#validation) lists its checks.

## Documentation

| Document | Purpose |
| --- | --- |
| [Project guide](../README.md) | Overview, gate commands and qualification results |
| [Project design](../Design.md) | P3 implementation boundaries and design decisions |
| [P3 charter](../../../docs/projects/delegation-reliability-scope.md) | V1 scope and stable P3 acceptance IDs |
| [Baseline work item](../../../docs/work-items/0023-p3-native-baseline.md) | Native baseline and isolation decision |
| [TypeScript specialist guide](../specialist-ts/README.md) | HTTP routes, grants, resource bounds and PNG checks |

The [implementation status](#implementation-status) table links the handoff for
each later slice.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python | 3.14 | Use the frozen root workspace development environment |
| `livekit-agents` | 1.8.11 | Pinned dependency |
| P1 dependency | `agent-continuity[postgres]` | The package declares the matching public dependency for acceptance |
| HTTP dependency | None | The HTTP client uses the standard library, without an implicit or transitive HTTP dependency |
| Docker, room, model download or provider credentials | None | Not needed for the native baseline and the unit and socket tests |
| Real acceptance | Explicitly owner-installed P1 read-only work profile on local PostgreSQL | Importing a client performs no DDL |
| `TaskGroup` API | SDK `beta.workflows` module | This exact pinned API is exercised; it is not claimed to be generally stable across releases |

## Commands

| Task | Command | Notes |
| --- | --- | --- |
| Run the native baseline | `.venv/bin/python -m delegation_reliability` | From the repository root; prints one safe JSON report |
| Run the project tests | `.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v` | From the repository root |
| Run a registered lab runner | `.venv/bin/python -m harness run P3-01` | From the repository root; use `P3-03` or `P3-11` for the other runners |
| Run the baseline in an installed environment | `python -m delegation_reliability` | Use that environment's interpreter |
| Run the baseline console script | `delegation-native-baseline` | Declared by the distribution for the same entry point |

From the repository root after its documented frozen development bootstrap:

```sh
.venv/bin/python -m delegation_reliability
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

The baseline module prints one safe JSON report. Redirect it to an ignored local
evidence file when retaining an experiment. The report contains fingerprints and
finite outcomes, not the submitted note or the full conversation.

In an installed environment, run the same baseline with that environment's
interpreter as `python -m delegation_reliability`. The distribution also declares
the `delegation-native-baseline` console script for the same entry point. The
configured examples that this guide links are repository files under
`projects/delegation-reliability/examples`; the wheel does not include them.

The repository gate commands for each slice are listed in the
[project guide](../README.md#validation).

## Acceptance, execution and completion

These facades accept work through P1, run issued attempts against the specialist,
deliver results and request guarded action. Use declared exports from
`delegation_reliability` or the documented `coordinator`, `case_adapter`, `runner`,
`completion`, `delivery_contract`, `action_adapter`, `http_client` and `contracts`
modules:

| Module | Provides |
| --- | --- |
| `contracts` | `DelegationRequest` and `Scope` |
| `coordinator` | `DelegationCoordinator` and `CaseAuthorityPort` |
| `case_adapter` | `ManagedCaseAuthority` and `CaseBinding` |
| `http_client` | `SpecialistClient`, `SpecialistEndpoint` and `SpecialistResultObservation` |
| `runner` | `DelegationRunner` and `DelegationRun` |
| `delivery_contract` | `ResultDeliveryPort`, `DeliveryBinding`, `DelegationDelivery` and `ResultReceiverPort` |
| `completion` | `DelegationDeliveryClient`, `FixedPolicyDeliveryClient` and `ChannelPolicyDeliveryClient` |
| `action_adapter` | `DelegationAuthorizer`, `ExactManagedCaseAuthority`, `ActionBinding` and `DelegationAuthorization` |

### Coordinator and case adapters (P3-I06)

Application startup supplies `DelegationCoordinator` with a credential-bound P1
`TaskExecutionPort`, a trusted `Scope` and a `CaseAuthorityPort`. The coordinator
binds scope to this trusted composition. It checks the public credential-bound scope
before any port operation, so a misbound client cannot first accept another scope's
body.

| API | Behavior |
| --- | --- |
| `submit` | Snapshots a strict, immutable `DelegationRequest` before its first port call |
| `find` | Uses the request's logical ID |
| `get` | Uses the returned P1 work ID |
| `cancel` | Uses the returned P1 work ID and a stable cancel command |

- Exact semantic replay returns the original bytes and deadline. Only attempt
  transport metadata may differ.
- Changed input under the same ID conflicts, including during concurrent admission.
- An ambiguous acceptance acknowledgement is reconciled by an original-key read,
  without a second submission.

P1 atomically owns the complete immutable accepted bytes and their computed digest,
and it keeps the only durable acceptance record. The version-1 acceptance profile
issues no attempt. The coordinator is acceptance-only: it starts no scheduler or
specialist attempt. Replay, inspection and cancellation of accepted work remain
available after a case change or expiry.

#### Case adapters

`CaseAuthorityPort` is a mandatory read preflight for new work.

| Adapter | Reads | Trusted bindings | Cancellation after a committed intent |
| --- | --- | --- | --- |
| `ManagedCaseAuthority` | The public P1 managed-case projection | At most 128 `CaseBinding` values mapping trusted logical IDs to exact P1 task and case IDs | Not distinguishable, so committed cases fail closed with `case_state_unavailable` |
| `ExactManagedCaseAuthority`, added by I07B | The authenticated exact read of the public P1 `case_control_api` (`CaseControlClient`) | `ActionBinding` values; each fixes the logical IDs, exact task and case, actor, scope and schema | Observed exactly, even after intent commitment |

Ordinary uncommitted cases can progress through `ManagedCaseAuthority`. For
`ExactManagedCaseAuthority`, the authenticated identity therefore includes actor,
scope and schema, and no request payload selects authority.

A preflight read cannot grant atomic current-case, mutation or action authority.
Neither read adapter grants action authority.

#### Coordinator ownership

The application owns the case client. The coordinator owns and closes its injected
work client. The coordinator never injects `ResultDeliveryPort`; the separately
composed `DelegationDeliveryClient` from I07B implements it. Delivery and exact
action each own their public P1 client. The application owns the shared result
inspector and exact case client, and closing a facade never closes that shared
inspector.

### Specialist HTTP client

`SpecialistClient(SpecialistEndpoint(port), authorization)` supports async `invoke`,
`status`, `cancel`, `invoke_observed` and `close`.

- It uses native asyncio streams to literal `127.0.0.1` only: one request (POST) per
  socket, with no ambient proxies, redirects or retries.
- Responses require exact bounded framing and typed schema, correlation and expiry
  checks.
- `invoke` remains strict and candidate-only. `invoke_observed` returns a
  `SpecialistResultObservation` with candidate or expired timeliness, under the same
  strict framing, identity and total transport budget. This enables historical
  result retention.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active calls | 4 | `SpecialistClient` | Default; validated overrides remain finite |
| Total time | 5 seconds | `SpecialistClient` | Default; validated overrides remain finite |
| Cleanup observation | 1 second | `SpecialistClient` | Default; validated overrides remain finite |

A validated candidate still needs trusted source facts and current case and action
checks. Caller timeout or cancellation does not prove that remote computation
stopped.

Both the Python and TypeScript libraries retain owned work until actual settlement
after waiter cancellation or timeout. Owned transport, case and P1 operations keep
their capacity, and no waiting queue or timer frees a live slot. Finite close
reports `cleanup_incomplete` while held work remains; retry close after actual
settlement.

HTTP metrics distinguish framed received responses from validated public
observations. Named logger events use only fixed operation, code and outcome values.
Handler setup, execution and flush budgets, and export remain application
responsibilities.

### Issued execution runner (P3-I07A)

`DelegationRunner` runs explicit issued attempts through P1's separately
owner-upgraded version-2 public `ExecutionPort`. It provides explicit issued
invocation, strict grounded result validation and P1-owned durable bytes. The
accepted wire attempt remains proposed metadata, and a proposed wire attempt alone
is never sufficient to invoke.

#### Runner construction and limits

Application startup supplies a credential-bound public P1 `ExecutionPort` already
bound to the verified `WorkScope` and an explicitly upgraded v2 profile. The runner
also takes the trusted scope and owner UUID, bounded immutable policy evidence, a
case-read port and a typed specialist client:

```python
DelegationRunner(
    executions=...,
    scope=...,
    owner_id=...,
    specialist=...,
    case_authority=...,
    evidence=...
)
```

The runner owns and closes both the execution and specialist clients. The
application owns the case-read adapter.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Evidence records | At most 4 verified records | Runner evidence | Defensively copied |
| Evidence size | 16 KiB | Runner evidence | Defensively copied |
| Active runner calls | 1 by default | `DelegationRunner` | Configured active calls stay at most 4 |
| Caller observation | 5 seconds | `DelegationRunner` | Default |
| Cleanup observation | 1 second | `DelegationRunner` | Default |
| Logical lease | 10 seconds | P1 default | Remains authority policy |
| Issued attempts | At most 3 | P1 | Remains authority policy |

Actual retained HTTP threads and streams have their own finite occupancy.

#### Running one attempt

`run_once(work_id, command_id)` issues one stable command, which requests one
durable attempt.

1. Only newly created issuance can invoke. A replayed or ambiguously acknowledged
   issuance is inspected without another invocation.
2. Before physical HTTP, a fresh P1 observation must still show the same exact
   current, uncancelled running grant, and the runner checks local abandonment and
   expiry. This is an eligibility observation, not a physical execution fence. It
   cannot fence a process paused after the check or guarantee a remote stop.
3. The wire correlation ID is `attempt_` followed by the issued UUID's 32
   hexadecimal characters, which satisfies the frozen letter-leading wire grammar.
   The original accepted bytes, logical fingerprint, deadline and proposed attempt
   remain unchanged.
4. An ambiguous result commit is reconciled by its exact attempt, without another
   write.

A timed-out or cancelled caller does not free its owned task or prove a remote stop,
and late known results may still be retained as history. No later HTTP can start
once that caller abandoned issuance.

The specialist authenticates its own principal, capability and evidence grants. The
HTTP service does not independently verify P1 issuance. P1-issued execution is
enforced by this runner path, while direct development HTTP computation grants no
durable result or business authority.

#### Results and applicability

P1 alone records bounded opaque result bytes and their time, lease and cancellation
disposition, which it decides from database time. `eligible_at_commit` is not
semantic or current-action approval. P3 independently checks identity, evidence and
factual policy claims before storing even late bytes, including late history.

The returned `DelegationRun` separates what was invoked, the recorded result and the
current view. `inspect(work_id)` reads the original accepted input and the current
P1 attempt and result, then returns fresh read-only applicability: candidate,
clarification, outdated, cancelled, expired or unavailable.

- A case-read failure returns unavailable. A revision change returns outdated while
  retaining the computation. Both are read observations, not atomic
  current-at-commit decisions.
- A valid old computation may remain historical while an independently issued
  current attempt progresses, so a superseded recorded result can differ from the
  current view. P1's public `result(work_id, attempt_id)` keeps old result history
  inspectable.
- The runner itself accepts no action or delivery. No result authorizes a booking
  mutation or claims delivery by itself.

### Result delivery (P3-I07B)

`DelegationDeliveryClient` implements `ResultDeliveryPort`:

```python
DelegationDeliveryClient(
    results=...,
    deliveries=...,
    receiver=...,
    scope=...,
    evidence=...,
    bindings=(DeliveryBinding(case_id, conversation_id, recipient_id),)
)
```

- It independently reconstructs the original accepted request, issued result,
  canonical bytes, evidence and applicability.
- Its finite trusted `DeliveryBinding` maps a case and conversation to one recipient
  and the configured receiver.
- P1 prepares immutable stored-result bytes before any receiver I/O.

| API | Behavior |
| --- | --- |
| `deliver_once(work_id)` | Returns a `DelegationDelivery` with an independent missing, prepared, unknown or accepted state, the immutable P1 snapshot and whether this call invoked the receiver |
| `inspect(work_id)` | Reads the current P1 delivery snapshot without receiver I/O |

`deliver_once` also reconciles possible sends:

- Only a newly created P1 begin, which commits a new possible-send marker, permits
  `receiver.accept`.
- An existing possible send uses `receiver.find` only. Absence stays unknown until a
  later recovery policy exists.
- Known original receipts survive expiry, work cancellation and case invalidation.

Receiver acceptance means the receiver retained the bytes. It is separate from
playback and human acknowledgement.

### Exact confirmation and guarded action (P3-I07B)

`DelegationAuthorizer` exposes `authorize_once(work_id, confirmation=...,
command_id=...)` and `inspect(work_id)`:

```python
DelegationAuthorizer(
    results=...,
    actions=...,
    scope=...,
    evidence=...,
    bindings=(ActionBinding(case_id, task_id, authority_case_id, authority_actor_id,
                            authority_scope_id, case_schema),)
)
```

- `confirmation` must be the separately supplied exact public P1 `Confirmation`,
  with `explicit=True`, for the original result's trusted task, case, revision and
  quote and a factual eligible result. The authorizer never infers consent from a
  candidate.
- P1's public `ActionPort` validates current work and result eligibility and the
  case revision, quote and confirmation atomically with intent commitment and the
  action receipt. A prior case read cannot replace this guard. A cancellation that
  arrives after the P3 preflight therefore rejects new intent.
- The returned `DelegationAuthorization` contains the stable action receipt and a
  reconciled flag. Known committed receipts remain facts after later cancellation,
  and replay or ACK loss reads the original command without another authorization
  write.
- No supplier I/O happens in this facade. The specialist receives no mutation
  permission, and the existing P1 mutation worker owns the eventual effect.

### Shared completion facade rules

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active calls | 2 | Each completion facade | Default |
| Caller observation | 5 seconds | Each completion facade | Default |
| Cleanup observation | 1 second | Each completion facade | Default |

Each completion facade owns its delivery or action P1 client, and the delivery
facade also owns its receiver. The application owns the shared results inspector
and case client.

- Inputs and nested returned values are defensively reconstructed before awaiting.
- A cancelled or timed-out waiter retains actual owned work until settlement. Close
  reports `cleanup_incomplete` while that work remains held.
- Ambiguous acknowledgements read only the original identity. A lookup failure
  preserves `acknowledgement_unknown`.
- Known original receipts remain facts after later cancellation, expiry or revision.
- Fixed `delegation_completion` log events and numeric process-local counters
  contain no submitted input, identifiers, secrets or raw dependency exceptions.

### Composition and inspection example (P3-I08)

The standalone [policy completion example](../examples/policy_completion.py) imports
only declared public APIs. It composes explicit application ports: two configured
`DelegationCoordinator` clients, one `DelegationRunner`, a `ResultDeliveryPort`
delivery facade and a `DelegationAuthorizer`. Pass them to `run_completion` with a
strict `DelegationRequest` and a separate exact `Confirmation`.

`run_completion`:

1. copies the request and the already supplied exact confirmation before awaiting;
2. concurrently submits the original identity, where equal concurrent submissions
   may return one created acceptance or original replays and changed input still
   conflicts through the coordinator;
3. reads the actual accepted input and result;
4. delivers the result and requests guarded action; and
5. returns safe identity, digest and state fields, with human acknowledgement
   retained as unobserved.

Explicit execution and confirmation command IDs keep replays bound to original
identities. Passing an invalid or non-explicit confirmation fails without deriving
consent from the specialist answer.

`inspect_accepted(work_id, coordinator=..., runner=..., delivery=..., authorizer=...)`
only reads. It returns distinct accepted, execution, delivery and action snapshots
without invoking, delivering or authorizing.

The caller configures and closes every client, installs profiles and initializes the
receiver beforehand. The example creates no schemas, receiver, background workers or
inference clients, and importing it performs no setup, I/O or model work.

The registered P3-03 and P3-11 lab runners are described in the
[project guide](../README.md#registered-acceptance-runners). They qualify rejection
bounds, not image extraction or model quality. The later
[document client](#document-extraction-client-p3-i16) adds bounded PNG checks and a
finite scripted field mapping, which is not optical character recognition (OCR).

### Standalone composition example (P3-I15)

[`standalone_policy.py`](../examples/standalone_policy.py) composes configured public
ports and actually calls `policy_completion.run_completion`. The application
supplies immutable evidence, finite case and receiver mappings and a separate exact
operator `Confirmation`. Importing it starts no listener, migration or worker.

Successful configuration transfers client ownership to the application. Close
attempts independent owners within each tier, preserves the first failure and
retains cleanup after caller abandonment. Shared readers stay open until dependent
clients settle, and an explicit close retry observes those same owners. Owner
installation and the synthetic leased worker remain separately labelled test
tooling.

The repository's package gate builds this distribution from fresh artifacts and
checks it as an installed consumer, offline and in an explicitly configured lab. Its
assertions and outcomes are in the
[project guide](../README.md#standalone-package-gate), and the
[standalone handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records exact outcomes and remaining work.

## Result metadata

These clients keep P3's own versioned metadata about P1 results. P1 remains the
source, result, case, delivery and action authority. Every storage change is an
explicit owner setup or upgrade. Serving code never installs, upgrades, creates or
repairs a schema.

### Result projection (P3-I09)

The projector consumes P1's generic result-only v4 feed through the public
`ResultFeedPort` and `ExecutionPort`. Accepted input, attempts, opaque result bytes
and completion receipts stay in P1.

#### Projection setup

Explicit owner setup uses `continuity_lab.work_admin.upgrade_work_schema_v4` and:

```python
projection_admin.install_projection_schema(
    owner_settings,
    binding=ProjectionBinding(source_id, WorkScope(tenant_id, account_id)),
    limits=ProjectionLimits(max_records=3000)
)
```

- The owner v3-to-v4 work upgrade adopts existing results with stable source and
  event identities and origin `adopted_history`. Adoption order is deterministic,
  but it does not reconstruct the original commit order.
- Owner setup is a separate command, and runtime never creates or repairs a schema.
  A repeated exact install validates and preserves rows. Changed limits, source or
  scope fail rather than silently rebind.
- Serving receives only existing runtime settings, `WorkDirectory` and
  `BearerToken`. `open_result_feed_client` supplies the immutable `source_id`, and
  `open_projection_client` binds that source and the authenticated scope.

#### What projection v1 stores

Projection v1 has three tables: schema metadata, one scoped source checkpoint and
bounded result-reference observations. It copies no result body. It owns no queue,
delivery or action ledger, or source acknowledgement.

Each `schema_version=1`, `kind=result_projection` row references the exact source and
event, the work, attempt and command, the issued identities, and the request and
result digests. Its validation status, validated or rejected, is separate from its
immutable applicability. The applicability record holds `as_of_non_atomic`, execution
status, cancellation and current attempt, execution observation time, case read
availability, revision, cancellation and time, and evaluation time. These come from
separate reads.

- Case revisions can change without a result event. A case-only change creates no
  feed event and does not rewrite a prior candidate.
- A stored candidate describes past reads and never authorizes an action. Current
  action permission always comes from P1's atomic same-transaction work/result plus
  exact case-confirmation guard.
- Foreign or unavailable case data is discarded and represented by unavailable
  fields. It is never copied into diagnostics or storage and cannot invent current
  applicability.

#### Projection capacity

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Stored references | At most 3,000 by default | Projection v1 | Configurable from 1 to 30,000 |
| Metadata value | 8 KiB | Each canonical metadata value | None |
| Raw metadata | About 23.44 MiB at the default cap | Projection v1 | Excludes indexes, write-ahead log (WAL) and backups |
| Source sequence | Signed int64 | Source sequences | Retention remains independently bounded |

Reaching the cap raises a capacity error, with no checkpoint advance. This slice has
no pruning, tombstone or automatic cap expansion, and a future retention policy
cannot permit identity reuse.

#### Running the projector

```python
ProjectionProjector(
    events=feed,
    executions=execution_client,
    projections=projection_client,
    scope=scope,
    evidence=records,
    case_authority=exact_case_adapter
)
```

The projector owns its three clients. The application owns the shared case adapter
and the projector's close lifecycle.

| API | Behavior |
| --- | --- |
| `await project_once(limit=4)` | Consumes four contiguous source references by default and at most eight, then stops |
| `checkpoint()` | Read-only, on the projection client |
| `get(work_id=..., attempt_id=...)` | Read-only, on the projection client |

| Condition | Outcome |
| --- | --- |
| Definite invalid P3 input, result or facts | Quarantined with fixed rejection codes and checkpointed, so later useful results progress |
| Missing or changed source identities, or unavailable execution reads | The step stops without advancing |
| Unavailable source | The checkpoint stays unchanged |
| Exact complete-batch replay | Returns the original metadata rather than reclassifying it |
| Competing partial batches, partial overlap or a moved checkpoint | Fails with `checkpoint_conflict`; there is no retry loop, and the application may explicitly schedule a fresh step |
| Unknown write | Looked up exactly once, without another apply; a failed or absent lookup keeps `acknowledgement_unknown` |

If an unknown write's exact rows are found, before and after describe the actually
observed checkpoint.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active calls | 2 | `ProjectionProjector` | Default; configurable within finite bounds |
| Caller observation | 5 seconds | `ProjectionProjector` | Default; configurable within finite bounds |
| Cleanup observation | 1 second | `ProjectionProjector` | Default; configurable within finite bounds |

Timed-out or cancelled waiters retain actual thread and port capacity until
settlement. Abandoned pre-write steps cannot later apply. `close` reports
`cleanup_incomplete` while work remains. Fixed `result_projection` operation, code
and outcome logs and numeric metrics contain no IDs, bodies, credentials or
dependency text, and a telemetry failure cannot alter stored truth.

The [public example](../examples/result_projection.py) exposes explicit bounded
projection and separate inspection through already configured public clients,
without DDL, background tasks or inference. I09 adds no source acknowledgement,
autonomous delivery, scheduler, refresh policy, action or provider call; I11 later
adds refresh separately.

### Delivery-only processing (P3-I10)

P3-I10 extends an existing projection with an explicit v1-to-v2 owner upgrade. The
original three tables remain. Two new tables, `processing_control` and
`processing_acks`, add a fixed receiver and route policy, a discovery position and
immutable terminal event observations. These metadata tables do not duplicate P1
result bodies, delivery plans or receipts, action state or execution ownership.

#### Processing setup

Owner setup calls:

```python
projection_admin.upgrade_projection_schema_v2(
    owner_settings,
    policy=CompletionPolicy(receiver_id, bindings)
)
```

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Trusted `DeliveryBinding` mappings | Up to 32 | Processing policy | Case, conversation and recipient mappings |
| Receiver | One receiver UUID | Processing policy | None |
| Policy bytes | 16 KiB | Processing policy | Remain fixed across restart; a changed policy conflicts |

- The upgrade preserves every v1 row, checkpoint and limit. Original source
  identity, metadata bytes, checkpoint and limits survive upgrade, interruption,
  versioned-profile backup and restore, and repeat.
- Repeated v1 installation and old public projection clients remain compatible with
  v2, including new result writes.
- The tested versioned-profile row export and restore is separate from `pg_dump`.

`open_processing_client` opens an existing v2 profile:

```python
open_processing_client(
    settings=runtime_settings,
    directory=...,
    token=...,
    source_id=...,
    policy=...
)
```

Its public reads are `checkpoint()` and `acknowledgement(event_id=...)`. Bounded
paging and ACK writes are private to `CompletionProcessor`.

#### Running the processor

```python
CompletionProcessor(
    processing=client,
    source=feed,
    delivery=facade,
    results=reader,
    scope=scope,
    evidence=records
)
```

The processor owns its processing, feed and delivery clients. The application owns
the shared result and case readers and the processor lifecycle. The additive
`ProcessingDeliveryPort` supplies a copied scope, `receiver_id` and bindings;
existing `ResultDeliveryPort` consumers keep their original interface. The
[public example](../examples/result_processing.py) exposes `process_results` and
`inspect_ack` using declared imports, without setup or implicit tasks.

`process_once(limit=4)` examines at most eight unACKed projected references in
total, four by default, across at most two queries and one wrap.

- The scan cursor is for discovery only. It may pass an unknown event A so that a
  later eligible event B progresses. The terminal watermark never skips A: it
  advances only across contiguous terminal ACKs.
- Only a known exact P1/receiver receipt, or a definite rejected or historical
  not-required-as-of decision, creates a terminal ACK. Rejected content and
  not-required-as-of decisions stay distinct from accepted receiver receipts.
- A terminal ACK acknowledges this delivery policy's processing. It grants no
  action, source acknowledgement or human consent. Processing does not call an
  authorizer or create human confirmation, and receiver acceptance is not playback
  or human acknowledgement.
- Exact source, event, work, attempt, request, result and projected-row identity and
  the fixed policy bind each acknowledgement. Same-case conversations cannot
  exchange recipients. A source, scope or fixed-policy mismatch cannot create an ACK
  or retarget a recipient.

#### Uncertain and unavailable state

- A known exact original receipt remains a fact. It is considered before fresh case
  applicability, including during a later case-read outage.
- A possible send with no receiver receipt stays unknown after restart, case change,
  cancellation or expiry, and gets no ACK. It is lookup-only and never
  automatically accepted again.
- Unavailable case or delivery state is deferred. Unavailable or changed source
  state cannot be invented.
- Stored projection observations cannot authorize a new delivery. Only the existing
  facade permits a new receiver accept, after P1 `begin.created`, and it performs its
  fresh result and case preflight and P1 eligibility check. Those reads do not
  establish an atomic cross-authority case or recipient revocation fence.
- There is no automatic retry, recipient rebase or event-derived action.

Dependency errors during a step:

| Condition | Outcome |
| --- | --- |
| Transient dependency error from the result feed, the delivery client or the direct result read | Recorded as a per-row, unACKed `unavailable` outcome; the scan continues |
| Acknowledgement unknown from the delivery client or the result read | Keeps its unACKed `unknown` outcome |
| Definite invalid or unauthorized error | Still fails the step |

The transient codes are capacity, closed, storage unavailable, acknowledgement
unknown, deadline exceeded, cleanup incomplete and request aborted.

#### Concurrency and reconciliation

Each ACK and its scan and control revision commit atomically in one coherent
repeatable-read CAS snapshot. A concurrently appended projection remains outside that
snapshot and is visible on the next read. Concurrent replay returns the original
acknowledgement.

| Condition | Outcome |
| --- | --- |
| Definite serialization or checkpoint conflict | Remains `checkpoint_conflict` |
| Ambiguous commit | Remains `acknowledgement_unknown` |

- Each conflict or ambiguous commit may look up its exact original ACK once, without
  another write. A failed or absent lookup preserves its code.
- Original returned observations are defensively copied and cannot claim another
  caller's advancement.
- Partial multi-event progress can remain committed after a later event fails.
  Public exact ACK and checkpoint reads expose those facts.

#### Processing capacity, defaults and telemetry

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| ACK count | The v1 retained-record cap | Processing ACKs | The same cap bounds projected references |
| ACK size | At most 4 KiB | Each ACK | None |
| Raw ACK bytes | About 11.72 MiB at the default 3,000 records | Processing ACKs | In addition to at most 23.44 MiB of projection metadata; indexes, WAL and backups are extra |
| Active processing calls | 2 | Each processor instance | Default |
| Caller observation | 10 seconds | Each processor instance | Default |
| Cleanup observation | 1 second | Each processor instance | Default |

Blocking writes retain slots and owned exceptions through timeout or cancellation,
and close reports incomplete until actual settlement. An abandoned read cannot start
a later ACK write. `close()` takes effect between rows: a write already in flight
completes, no later row, delivery or ACK starts, and the caller receives
`request_aborted`. SQL and receiver work occurs outside conversational loops, and no
external receiver I/O occurs under a P3 metadata lock.

Fixed `result_projection` operation, code and outcome logs omit submitted values and
IDs. Numeric processing counters report examined rows, terminal ACK observations,
unknown or unavailable observations and exact ACK reconciliations. They are local
observations, not unique SQL row counts or exported metrics. Throwing telemetry
cannot change stored truth.

I11 adds a separate explicit refresh and display policy. Source incarnation rotation
and broader action and recovery remain later work.

### Applicability refresh and display retention (P3-I11)

P1 remains the source, result, case, delivery and action authority. The explicit
owner `upgrade_projection_schema_v3` (projection v2 to v3) adds only a fixed
`RefreshPolicy` and refresh control, per-event heads and immutable refresh command
receipts over an existing v2 profile. Original projection and processing ACK bytes
are preserved. Use `open_applicability_client` with the same explicit source and
scope binding and policy. Serving never installs or upgrades storage. Existing
projection and processing clients remain compatible on v3.

#### Refreshing one result

```python
ApplicabilityRefresher(
    events=feed,
    executions=execution,
    applicability=metadata,
    scope=scope,
    evidence=records,
    case_authority=exact_case
)
```

The refresher owns its three injected feed, execution and metadata clients. The
application owns the shared exact case reader.

`refresh(work_id, attempt_id, command_id, expected_revision)` observes exactly one
retained work and attempt under a stable UUID command and an expected per-result
revision.

- Replay of an equal command returns its original historical receipt before any new
  read or capacity check, even after hide, cancellation or a current-source outage.
  It is not a fresh current-state read. A changed target or expected revision
  conflicts.
- A new command verifies the current exact feed event, the historical grant, the
  exact source, event, attempt, request and result identities and bytes, and the
  trusted evidence. It then separately reads current work (execution) and case
  state.
- A local revision CAS orders metadata only. It grants no atomic cross-authority or
  action permission.

#### Classifications and retained evidence

The current, outdated, invalidated, unavailable and rejected classifications are
explicitly non-atomic as-of observations, never action or delivery permission. Raw
`as_of_non_atomic` fields remain distinct from the effective classification and from
retained invalidation witnesses. Candidate and clarification remain distinguishable,
and neither is human consent.

- Verified higher revisions, different-attempt witnesses and cancellation evidence
  cannot be erased or silently cleared by a stale or unavailable read.
- Host deadline expiry is explicitly local and as-of. It is never a P1 database-time
  receipt.
- A stored eligible result remains eligible at its original commitment even after
  its old grant lease elapses: a postcommit grant-lease expiry does not invalidate
  it.
- Existing P1 and receiver receipts and terminal processing ACKs remain original
  facts after invalidation.

#### Display retention and limits

| API | Behavior |
| --- | --- |
| `ApplicabilityClient.command` | Preserves the exact authenticated original facts |
| `inspect` | Preserves the exact authenticated original facts |
| `hide_display` | Stores one stable, idempotent, permanent presentation tombstone, independent of the refresh revision |
| `display` | Returns that tombstone marker |

- Original projection, refresh and ACK reads, inspect and replay still work after
  hide, and the processor continues to examine hidden unresolved events.
- No protected row or identity is deleted, expired or made new, and hide reclaims no
  capacity. Retention and replay last for the profile lifetime. There is no time to
  live (TTL) or cleanup daemon.
- New identities fail closed at capacity, while reads and replays remain available.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Total refresh commands | 3,000 by default | Refresh metadata | Configurable to a maximum of 30,000 |
| Refresh commands per result | 4 by default | Each result | Configurable to a maximum of 8 |
| Receipt size | At most 4,096 bytes | Each refresh receipt | None |
| Body allowance | 11.72 MiB by default | Refresh metadata | Before indexes, WAL and backups; not measured disk capacity or throughput |

#### Refresh ownership, errors and telemetry

The [public example](../examples/result_applicability.py) supplies `refresh_result`,
`inspect_result` and `hide_result` on configured clients, with no DDL, implicit
scheduling, provider calls or import-time I/O.

- Waiter timeout or cancellation retains actual tasks and threads until settlement.
  Close reports `cleanup_incomplete` while work is held.
- Ambiguous writes, stale CAS and definite CAS or serialization conflicts reconcile
  at most one exact original identity, never with another write.
- Fixed `result_projection` operation, code and outcome events and bounded local
  counters contain no bodies or credentials.

| Condition | Outcome |
| --- | --- |
| Transient source failure | `storage_unavailable` |
| Busy (capacity) or closed P1 read | Also `storage_unavailable`, because the refresher shares the completion processor's mapping |
| Mismatched immutable source data | `invalid_source_state` |

The tested populated quiescent profile-row restore preserves the exact captured cut.
It does not claim recovery of a stale branch that omitted later authoritative
history. P1 runtime, schema and source-incarnation behavior are unchanged.

## Behavior under races, deadlines and process loss

Slices I12 to I14 validate the facades above under actual races, deadlines and
process loss. They add no new runtime API, schema or execution owner. This section
states the resulting guarantees and limits for applications. The schedules,
assertion counts and bounds are in the [project guide](../README.md#validation).

### Guarded action under races (P3-I12)

No new P3 or P1 runtime module, API or schema is required for I12. The configured
[public example](../examples/policy_completion.py) composes the existing
credential-bound ports with an exact caller confirmation, and `inspect_accepted`
reads accepted input, execution, result receiver and action facts without
authorizing.

- The race proof uses a cooperating persistent synthetic supplier. An admitted
  noncooperating external request remains uncertain.
- Display and applicability metadata never grants action permission. Exact
  confirmation never comes from result content, and receiver acceptance never
  establishes human acknowledgement.
- Full recovery and media qualification and the remaining charter rows stay
  separate.

### Deadlines and cancellation (P3-I13)

Authority decisions use P1 database time after admission. A deliberately
noncooperating test-only Node peer can finish after cancellation or expiry. Its
immutable late facts stay recorded and ineligible, regardless of a claimed producer
completion timestamp. The normal specialist is unchanged.

- Business cancel request, running non-durable remote ACK, lost ACK, recorded
  result, as-of refresh and exact atomic action permission are independent facts.
- Waiter abandonment retains real I/O and does not itself business-cancel. Close
  remains incomplete while held work exists.
- A successful result is not retroactively invalidated by its old lease expiry.
- Fresh, separately confirmed current work still progresses through the configured
  public completion example with one fake effect.

### Process recovery (P3-I14)

The configured public [completion example](../examples/policy_completion.py) and the
existing clients are sufficient for the selected I14 process-recovery composition. No
new runtime API, execution ledger, migration or import-time work is introduced.

- Original accepted input, grant owner and command, immutable result and known
  receiver and action receipts survive fresh Python processes.
- Replaying the original issuance never invokes again. A distinct caller-supplied
  command may invoke only when P1 actually creates a current eligible attempt after
  observing that the old lease expired.
- An unresolved possible send remains lookup-only; absence is not permission to
  retry. Useful independent completion still receives its own exact receipt and
  processing ACK.
- A separately supplied exact confirmation remains necessary for the atomic P1
  action guard, and the existing leased worker alone applies the fake effect.
- No result-derived consent, automatic action or accept retry, or physical
  exactly-once computation is claimed.

Early read-only recovery uses an explicitly synthetic case preflight in a separate
account, while completion uses actual public P1 case and quote clients. The recovery
fixture's Node journal is ephemeral observation, not durable work. The
[phase handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
is the stable qualification and provenance reference.

## Document and fixed-policy capabilities

### Document extraction client (P3-I16)

I16 adds the read-only `booking.extract_document` capability beside the existing
policy wire. Python exposes `DocumentSpecialistClient` and separate document request
and result codecs. The configured
[`document_extraction.py`](../examples/document_extraction.py) example accepts
explicit clients and requests. Importing it loads no source image, model, listener
or credentials; the application owns the configured evidence and clients.

- One scoped immutable PNG supplies four ordered fields: booking reference,
  property, check-in and check-out.
- Known values carry exact source and region witnesses. Missing and ambiguous values
  require clarification.
- Structural validity and exact correlation are checked separately from the
  independent synthetic-image factual oracle.
- Image text remains inert data. The finite scripted mapping is not OCR or general
  vision inference, and no mutation or notification permission comes from its
  output.

The TypeScript specialist checks the actual PNG bytes before provider entry: at most
2 MiB and 2048×2048, RGB8 or RGBA8 noninterlaced. Unsupported formats, animation or
ancillary chunks, truncation and trailing data fail closed. Its worker, deadline and
ownership rules are in the
[specialist guide](../specialist-ts/README.md#document-capability-p3-i16).

P1's public work operation remains policy-only. Image HTTP is not durable image
acceptance, issued execution, projection, delivery, confirmation or action. A
reviewed versioned P1 operation extension is required before that integration. Full
charter and release qualification remains separate. The
[image handoff](../../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records qualification, provenance and remaining gates.

### Fixed-policy version 2 contract and client (P3-I17)

I17 implements an explicit input and result version 2 for `booking.evaluate_policy`.
Version-1 canonical bytes and public defaults stay unchanged.

| Module | Provides |
| --- | --- |
| `delegation_reliability.fixed_policy_contracts` | `FixedPolicyRequest` and `FixedPolicyResult`, with strict parse, produce and encode functions |
| `delegation_reliability.fixed_policy` | `FixedPolicySpecialistClient` and `verify_fixed_policy_facts` |

Configure `FixedPolicySpecialistClient` and call `verify_fixed_policy_facts`, or pass
those configured ports to the
[`fixed_policy_evaluation.py`](../examples/fixed_policy_evaluation.py) example. A
transport-correlated result still needs that explicit factual check against the
supplied evidence records.

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
close retry remain explicit. The
[fixed-policy handoff](../../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records source, installed and affected compatibility results and retained failure
provenance.

### Durable fixed policy (P3-I18A)

The original `DelegationCoordinator` and `DelegationRunner` retain version-1
defaults. Explicit `FixedPolicyCoordinator` and `FixedPolicyRunner` compose policy
version 2 through the same public P1 work and execution ports and shared typed
ownership cores. P1 accepts opaque policy-operation bytes; P3 verifies their
versioned facts. Projection, refresh and action remain version-1-only. Version-2
delivery is described under [fixed-policy result delivery](#fixed-policy-result-delivery).
The [I18A handoff](../../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records this implementation and its selected qualification.

1. Construct `FixedPolicyCoordinator` with a public authenticated
   `TaskExecutionPort` and a trusted `CaseAuthorityPort`.
2. `submit` acknowledges the original immutable request through P1.
3. An explicit `FixedPolicyRunner.run_once(work_id, command_id)` then runs the work.
   The runner requires the original logical owner plus exactly two immutable scoped
   JSON `EvidenceRecord` values, each at most 4,096 bytes.

Only a newly issued current grant permits HTTP invocation. Replaying the original
command never grants a new invocation, and known results preserve their original
bytes and commit disposition.

`FixedPolicySpecialistClient.invoke_observed(request, evidence=records)` copies and
validates that exact pair of records before I/O, then verifies every fact and
witness, even on a late result. It returns the typed result, the observation time
and a separate candidate, clarification or expired classification. The existing
`invoke` method remains the correlation-only transport API. The TypeScript client
offers the same check as `invokeObserved(request, records)`.

The durable runner independently checks facts before P1 completion and when
inspecting a stored result. P1 eligibility uses fresh authority time and stays
separate from semantic validity and current case applicability. Missing or
conflicting facts clarify. Cancellation does not erase previously eligible result
truth.

The configured [`durable_fixed_policy.py`](../examples/durable_fixed_policy.py)
example receives explicit public clients, evidence and identities. It performs no
implicit DDL, provider setup or scheduling. To close, close independent owners
within a tier, await successful facade closure, then close shared case readers.
Incomplete close retains actual I/O and may be retried.

This slice introduces no new P1 storage version, supplier call, result action or
native or session owner. The repository's twelve-assertion durable journey is
described in the [project guide](../README.md#durable-fixed-policy-gate).

### Fixed-policy result delivery

The explicit `FixedPolicyDeliveryClient` delivers verified policy-v2 results, as
implemented under the
[result-return work item](../../../docs/work-items/0043-stable-result-delivery-and-return-context.md).

Construct it with a `FixedPolicyResultReadPort`, a public P1 `DeliveryPort`, a
structural `ResultReceiverPort`, a trusted `Scope`, exactly two immutable
`EvidenceRecord` values and `DeliveryBinding` entries. Imports start no listener,
migration, worker or implicit retry.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active calls | 2 | `FixedPolicyDeliveryClient` | Default |
| Caller budget | 5 seconds | `FixedPolicyDeliveryClient` | Default |
| Cleanup observation | 1 second | `FixedPolicyDeliveryClient` | Default |

- The facade independently validates the original accepted, issued and result bytes
  and both source witnesses.
- A new delivery requires candidate applicability and an eligible P1 begin. Missing
  or conflicting policy facts cannot be promoted by a forged candidate label.
- An original possible delivery performs receiver `find` only. A missing lookup
  remains unknown and does not grant another accept.
- A receiver receipt retains the original result digest. An SMS notice digest is
  different.

The client owns and closes its delivery and receiver ports. The application keeps
the shared result inspector and closes it only after delivery actually drains.
Cancellation stops waiting without business cancellation, and incomplete close
retains owners for an explicit retry.

Receiver acceptance, carrier delivery, playback, human acknowledgement and guarded
booking action remain separate. Current case applicability is observed across
separate reads and is not an atomic case fence across an external receiver commit.
The existing v1 delivery and action APIs stay compatible.

Selected source delivery and read qualification passed; the gates are described in
the [project guide](../README.md#result-return-gate). Original P2-input binding,
described under [origin-bound policy](#origin-bound-policy-version-3), and joined
native voice/SMS qualification remain separate.

## Native and channel-origin policy

### Native background policy (P3-I18B)

`NativePolicyApplication` and `NativePolicyAgent` compose the explicit policy-v2
facades with one supplied `AgentSession`.

#### Native setup

- Trusted setup freezes one positive-revision request, its original command and
  exactly two immutable JSON sources.
- Configure the runner with two slots, for one run and one concurrent read. Its
  default remains one.
- The model receives no scope, case, command or evidence-selection arguments.

#### Tool calls and admission

1. The tool acknowledges through P1 before its silent `ctx.update` releases the SDK
   foreground.
2. One retained `run_once` task is shielded from the SDK waiter. SDK cancellation
   means stopped waiting, never business cancellation.
3. Admission remains reserved until that task and the public facade pending counts
   actually settle. A timed-out wrapper alone cannot free the slot.
4. Once acceptance may have succeeded, repeated calls inspect the original work
   rather than issue another command. A definite initial submit-capacity rejection
   permits a later explicit call with the same frozen request and command; it
   schedules no automatic retry.

Close preserves actual owners and may report `cleanup_incomplete` until a later
explicit retry observes settlement.

#### Observation

`NativePolicyObservation` exposes a copied, closed JSON value of at most 4,096 UTF-8
bytes. It separates the original result and disposition from as-of applicability and
labels the application read completion time.

- No-work requires an actual original-key read. Unknown reads never invent fresh
  authority fields.
- Missing or conflicting facts retain null eligibility and full witnesses.
- The card cannot authorize an action. The data transfer object (DTO) supplies no
  invented current-case revision or case-observation timestamp.

#### Configured native example

The configured [`native_fixed_policy.py`](../examples/native_fixed_policy.py)
function accepts an already supplied session, application, room and exact browser
participant. Its first profile is real-time communication (RTC) text with one SDK
input owner and audio input and output disabled. The lab host owns fixed
authenticated session and observation routes and a separate in-memory operator
capability; an RTC token grants no privileged read.

SDK-local unit results do not establish PostgreSQL, RTC/browser, audio,
model-quality or full-release evidence. This application introduces no P2 runtime,
new queue or schema, autonomous retry or v2 action or delivery adapter. The
[native-policy handoff](../../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records implementation and selected qualification.

### Origin-bound policy version 3

Explicit `ChannelPolicyRequest` and `ChannelPolicyResult` wrap the unchanged
fixed-policy-v2 contract with input and result version 3, so the specialist still
consumes the unchanged policy-v2 contract. The six-field origin retains the P2
profile, original operation, input receipt, SHA256 digest and canonical UTF-8 byte
length. Public parse, produce and encode functions validate both fingerprints and the
complete wrapper bounds. No raw channel message belongs in P1 policy input.

| API | Behavior |
| --- | --- |
| `ChannelPolicyCoordinator.submit` | Preserves exact logical matching of the complete logical request |
| `accept` | Explicitly returns the first equal-origin winner, that is, the first accepted context across equal-origin retries, without renewing its deadline or evidence |
| `scope` property | Read-only configured identity, not a live authorization observation |
| `ChannelPolicyRunner` | Adapts issued version-3 history to the existing `FixedPolicyInvocationPort`, verifies the inner result and wraps it back into version 3 |
| `ChannelPolicyDeliveryClient` and `ChannelPolicyResultReadPort` | Retain the complete outer result bytes for delivery |

Both `submit` and `accept` preserve the original attempt bytes. Newly created work
must exactly match the submitted envelope and preserve every submitted byte.

Legacy public defaults stay v1 and v2. The application supplies all credential-bound
ports, immutable evidence and finite routes. These facades create no queue, worker,
native room, migration or provider composition.

HTTP drain and authority drain are separate. Applications close the HTTP host first,
then its service or coordinator, then shared case readers, retaining any incomplete
owner for an explicit retry.

The [origin-bound work item](../../../docs/work-items/0044-origin-bound-channel-policy.md)
records the unit and socket checks, the actual source assertions and the isolated
package qualification; the [project guide](../README.md#origin-bound-gate) gives
the counts. Installed actual repetition and the joined native/media journey remain
separate later evidence.

## Validation

Status labels follow the
[implementation status vocabulary](../../../docs/documentation-standards.md#implementation-status-vocabulary).

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Native baseline | `.venv/bin/python -m delegation_reliability` | One safe JSON report from the provider-free comparison | Implemented |
| Project tests | `.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v` | Native baseline checks, timeout, caller cancellation, safe error and log behavior and fake-port facade tests | Implemented |
| Registered lab runners | `.venv/bin/python -m harness run P3-01` | P3-01 lab assertions; use `P3-03` or `P3-11` for the other runners | Qualified |

The native baseline checks require identical input and result fingerprints, no
completed result while held, a useful read-only explanation before release, a real
SDK-observed final result, native task and group completion, and bounded cleanup.
Invalid or oversized inputs fail before session creation. Tests also cover timeout,
caller cancellation and safe error and log behavior.

These are orchestration observations, not model quality, physical audio, durable
acceptance, authenticated case authority or process recovery. Individual timings are
host observations, not benchmark percentiles.

Fake-port tests remain distinct from actual database and process evidence. The
repository gates that exercise this package against actual PostgreSQL, sockets,
processes and installed artifacts, with their assertion counts and selected
qualification, are listed in the [project guide](../README.md#validation).

## Next milestone

Fourteen full charter rows remain planned, and the project gate remains incomplete.
Remaining work for this package includes:

| Step | Outcome | Gate |
| --- | --- | --- |
| Add broader workloads, autonomous scheduling and real models | Broader workload, scheduling and real-model evidence | Later phase gates |
| Add source incarnation rotation and broader action and recovery to result processing | Result processing beyond the selected I10 and I11 scope | Later phase gates |
| Repeat origin-bound policy in installed actual runs and the joined native/media journey | Origin-bound evidence beyond the selected source and package gates | Separate later evidence |
| Qualify joined native voice/SMS result return | Result return in the joined journey | Separate later qualification |
| Complete the broader integrated release | Integrated P3 release | Local-ready V1 and Portfolio-ready V1 release gates |
