# Delegation Reliability Kit scope

Status: Active
Last reviewed: 13 November 2026

## Overview

Build a Python coordination library and a TypeScript specialist service that let a
LiveKit conversational agent delegate bounded work, continue the conversation,
and safely use a result after a timeout, restart, handoff, or request revision.
The portfolio evidence is correct collaboration behavior and measured overhead.

The [portfolio scope](../portfolio-scope.md) defines shared terminology, execution
modes and release policy. The [validation plan](../validation-plan.md) defines
evidence. This charter is authoritative for P3 behavior and acceptance IDs.

### Reference scenario

A synthetic traveller supplies a static booking screenshot and requests a date
change. A read-only document specialist extracts structured fields and evidence.
A read-only policy specialist evaluates a fixed, versioned synthetic policy using
verified booking details. The conversational agent asks questions while specialist
work is pending. A user revision makes an older answer inapplicable to the current
request. Only the case authority can accept an intent to change the fake booking.

After the tools/native-subagent baseline and deployment decision, start remote
implementation with one specialist. V1 has two named capabilities, which can share
one TypeScript service:
`booking.extract_document` and `booking.evaluate_policy`. Document extraction can
produce uncertain or missing fields, which require clarification. Policy results
must cite the supplied policy version and relevant rules. Neither specialist can
modify a booking, authorize a charge, send an SMS, or obtain additional tools from
an untrusted image or document.

LiveKit already offers tools, handoffs, supervisor patterns, and background
subagent delegation. Reuse them for local conversational control; measure them as
baselines before introducing independent services. Native AgentTask/TaskGroup
controls conversational subtasks; the P1 execution contract supplies independent
process recovery. Avoid implementing a second session/task runtime. Sources:
[workflow patterns](https://docs.livekit.io/agents/logic/workflows/) and
[background subagent delegation](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/).

## Implementation status

P3-I01/I02 establish the controlled scripted native baseline and remote-boundary
decision. I03/I04 add policy request/result/evidence contracts, service-principal
authorization and bounded ephemeral attempt permits in Python and TypeScript.
I05 adds the first scripted authenticated HTTP handler/client. I06 adds the Python
HTTP client and immutable coordinator submit/find/get/requested-cancel through
P1's public opt-in read-only work profile. Full canonical bytes, digest and original
deadline persist before acknowledgement; credential scope is checked before writes
and ambiguous acknowledgement reconciles the original key. The actual gate labels
its synthetic case preflight and independent socket probe: I06 issues no attempt.
I07A now adds a one-step explicit runner through P1-owned issued grants and durable
opaque result observations on the optional work-profile v2 upgrade. Only a newly
issued command invokes; semantic validation and read applicability remain separate
from current-case action authority. I07B adds explicit receiver-bound delivery and
a separately supplied exact human confirmation through P1 work-profile v3. P1
atomically validates work/result/cancellation/deadline and current case authority
before committing its action receipt and existing case intent together. The
existing leased worker performs the fake supplier action outside that transaction.
A receipt means accepted result bytes, never playback or human acknowledgement.
Selected phase gates passed for the first stale-A/current-B path, completing the
I07 implementation task. Selected later tasks through I17 add resumable applicability
and event processing, protected races, deadline/process recovery, installed
consumption, standalone image HTTP and versioned fixed-policy HTTP. The qualified
I18A prerequisite adds explicit durable policy-v2 facades over unchanged public P1
authority, preserving v1 defaults. Image execution and v2 projection/action remain
unsupported. I18B now implements one native background policy application and a
configured RTC text example; selected actual source/installed backend and browser
qualification passed in [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md).
The completed [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
adds selected explicit v2 delivery and P2 current-channel data reads. Original
P2-input binding and typed schema3 consumption are implemented in 
[0044](../work-items/0044-origin-bound-channel-policy.md). Focused unit/socket checks
and isolated package/fake-port qualification passed; the fourteen selected actual
source assertions passed. Broader media,
integrated handoff and full release remain planned. I08 adds concurrent independent-process same-ID/conflict evidence,
a public completion/inspection example and complete registered lab runners for
P3-01/P3-03/P3-11, each with a fresh passing report. Fourteen other rows remain
planned; these three do not complete project release or media qualification. See
the [durable-policy handoff](../work-items/0041-standalone-channel-and-durable-policy.md); earlier
[routing/acceptance](../work-items/0031-revision-routing-and-delegation-acceptance.md),
[baseline](../work-items/0023-p3-native-baseline.md) and
[contract/trust](../work-items/0025-p3-specialist-contracts-and-trust.md) work items
retain their original evidence scope.

### Current selected native and result-return checkpoint

P3-I17 standalone fixed-policy and I18A explicit durable-v2 qualification retain their
completed handoffs. The [I18B handoff](../work-items/0042-responsive-native-policy-and-compact-demo.md)
records one configured AgentSession tool and compact as-of result view. Selected
native RTC text qualification passed twelve backend/SDK assertions and three
browser groups in both source and isolated installed modes, plus eight separate
installed offline package assertions. Local SDK checks retain their narrower scope. No microphone, STT, TTS,
P2 durable native intake or physical playback claim belongs to that profile.

P1 remains the only acceptance/issuance/result authority. The native tool retains
one owned call through SDK waiter cancellation and wrapper timeout; it introduces
no recovering queue, new schema, business cancellation shortcut or mutation.

The completed [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
qualifies explicit backend v2 delivery and current-grant result data reads through
sixteen storage/four return source assertions. Its twenty-five-stage offline
package lane is separate from those actual source assertions. Receiver acceptance,
carrier delivery, playback and human acknowledgement remain distinct.

[0044](../work-items/0044-origin-bound-channel-policy.md) implements original
P2 input identity in schema3 wrappers, explicit coordinator/runner/delivery facades,
the narrow P2 operation client and a bounded application HTTP boundary. Unit/socket
checks and isolated package/fake-port qualification passed; its fourteen selected actual
source assertions passed. This prerequisite does not complete P3-I19's integrated handoff.
P2-I22 release, joined voice/text/SMS routing, restart/discovery, applicable provider
runs and the final video retain their later gates. Fourteen complete P3 acceptance
rows remain planned, with no new catalog registration: fifty-five definitions and
twenty-four registered runners remain unchanged.

## Ownership and dependencies

| Owner | Authoritative data |
| --- | --- |
| Case authority | Current case revision, verified facts, explicit authorization, accepted mutation intents. |
| Project 1 or standalone execution adapter | Accepted execution requests, attempts, durable deadlines, retry eligibility, worker ownership, external-effect records. |
| Project 3 | Delegation identity, capability, immutable input snapshot, result validation and applicability decisions, cancellation and routing metadata. |
| Project 2 or standalone delivery adapter | Channel association, accepted messages, delivery intents and observed delivery evidence. |
| LiveKit | Realtime media and native conversation/session behavior. |

Project 3 must not maintain an independent current-case revision or create a
second execution queue as competing sources of truth. Cache values only with their
version and revalidate through the authority before accepting an action intent.

The coordinator depends on three narrow interfaces:

- `TaskExecutionPort`: accept stable logical work, inspect it, request cancellation,
  and receive durable status/result events.
- `CaseAuthorityPort`: read a revisioned snapshot and conditionally accept a
  mutation intent against the current revision and explicit confirmation.
- `ResultDeliveryPort`: durably accept a result-delivery intent and report delivery
  evidence for an identified conversation or account.

The standalone example supplies small local adapters and a seeded synthetic case;
it does not require the Project 2 gateway or the full reference application. Its
persisted execution adapter uses Project 1's installed public contract. A deterministic
test adapter can implement the port for unit tests, but must not be used as
evidence of durable process recovery. The integrated example uses Project 1's
execution service and Project 2's routing adapter. Standalone use may depend on
P1's public narrow execution library without starting the complete P1 deployment.
It must not import sibling storage internals or create another scheduler.

## Required V1 behavior

| Area | Included behavior |
| --- | --- |
| Public SDK | Typed Python coordinator API; typed TypeScript handler and client contract; versioned JSON request and result schemas; useful errors and examples. |
| Remote boundary | One versioned authenticated HTTP interface invokes bounded work for a P1-owned attempt. Status, results and cancellation messages are correlated observations; they do not create a second durable queue. Preserve logical identity across transport retries. |
| Durable execution | Submit through a small execution interface. The integrated example uses Project 1 for persistence, retries, deadlines, and recovery. |
| Applicability | Match tenant, case, request revision, capability, and schema before accepting a result for current reasoning. Record outdated results as historical. |
| Action authority | Ask the case authority to validate revision and explicit authorization and atomically record a mutation intent. Specialists cannot execute that intent. |
| Conversation lifecycle | Continue ordinary conversation during slow work; route completed results to the current agent or channel after handoff or reconnect. |
| Cancellation | Expose cancellation requested, remote cancellation acknowledged, and result invalidated as distinct facts. Cancellation acknowledgement alone does not establish that computation stopped. |
| Resource limits | Bound in-flight work globally and per tenant, queue size, attempts, context bytes, image bytes and dimensions, result bytes, and deadlines. Use a simple fixed admission policy. |
| Observability | Correlate delegation, case revision, workflow, execution attempt, model request, result, and delivery intent; record decisions to reject or invalidate a result. |
| Compatibility | Contract tests between Python and TypeScript; reject unsupported schemas with an explicit version error. |

Configuration must state limits, timeout units, and overload behavior. An
overloaded service returns an explicit deferred or rejected outcome; an unbounded
in-memory queue is not an implementation of admission control.

P1 owns durable acceptance, attempts, retry/deadline eligibility and persisted
results. The TypeScript service handles a bounded invocation for an identified
attempt; any local active-attempt registry is bounded and does not independently
recover or reschedule work. Lost HTTP responses, duplicate invocation and late
results follow the P1 execution and P3 applicability contracts. Cancellation
acknowledgement is an observation, not proof of termination.

Bind each HTTP operation to a verified local service principal. Authorize tenant,
account and capability access before invocation or status/result/cancel lookup;
a scope field in JSON is not authentication. Image references resolve through a
scoped allowlisted adapter rather than arbitrary caller-selected fetch URLs. Test
missing/invalid credentials, forged scope and inaccessible evidence references.
A small local mechanism is sufficient; no enterprise identity platform is needed.

Use typed TypeScript handlers, runtime schemas and selected capability/provider
clients. Node Agents/RTC native dependencies are needed only if this process
actually hosts a Node realtime agent.

No full transcript is copied by default. Build an immutable, bounded context
snapshot with the facts and evidence required for that capability. Credentials,
mutable case objects, and executable instructions do not belong in that snapshot.

## Public contracts

These are APIs to implement; they are not LiveKit SDK methods.

```python
handle = await delegations.submit(
    request=DelegationRequest(...),
)
status = await delegations.get(scope, handle.delegation_id)
cancel = await delegations.cancel(
    scope, handle.delegation_id, reason="request_revised"
)
```

The TypeScript handler accepts the same versioned logical request and returns a
validated capability-specific result. Runtime schema validation is mandatory on
both sides; language types alone do not validate received JSON.

| Request field | Meaning |
| --- | --- |
| `schema_version` | Delegation envelope version. |
| `scope` | Tenant and account namespace bound to the authenticated service principal by a trusted adapter; never self-authorized JSON. |
| `delegation_id` | Stable logical work identity, retained across retries. |
| `case_id`, `request_revision` | Case and exact revision being answered. |
| `capability`, `input_schema_version` | Named capability and validated input version. |
| `context_snapshot` | Immutable bounded facts, policy version, and evidence references. |
| `deadline_at_ms` | Absolute UTC expiry in integer milliseconds; trusted observed time governs eligibility, and elapsed measurements use a monotonic clock. |
| `attempt` | Exact result attempt_id matching; attempt number remains request/live-permit metadata. Excluded from the logical input fingerprint. |
| `evidence`, `input_fingerprint` | Bounded scoped source versions/digests and canonical logical request fingerprint. |
| `result_route` | Stable logical destination resolved by the delivery adapter. It is not an arbitrary caller-supplied webhook URL. |

The current policy wire rejects unknown fields; correlation/causation diagnostics
belong to future transport instrumentation rather than additional v1 JSON keys.
Results include diagnostic completed_at_ms, which cannot revive expired work.

Results carry the request identity and revision, output schema version, structured
output or structured failure, evidence references, and producer/attempt identity.
Image references must resolve only within the authorized scope. The fixture and
live paths enforce the same image/context size limits.

Public outcomes include `accepted`, `running`, `completed`, `failed`, `timed_out`,
and `cancelled` execution status. Result applicability (`current`, `outdated`,
`invalidated`) and delivery status are separate fields. A result can complete
successfully and still be outdated or undelivered.

| Condition | Required API behavior |
| --- | --- |
| Same scoped ID and canonical request | Return the existing logical delegation. Transport retries may repeat processing attempts. |
| Same scoped ID with different request | Raise `IdempotencyConflict`; never silently replace the input snapshot. |
| Unknown or inaccessible identity | Return a scoped not-found/unauthorized outcome without revealing another tenant's work. |
| Unsupported schema or invalid payload | Reject with a structured validation/version error before accepting work. |
| Deadline already expired | Reject without starting model work. |
| Capacity exhausted | Return the documented overload outcome with bounded retry advice where applicable. |
| Invalid specialist result | Record validation failure; do not treat free text as an authorized action. |
| Result arrives after invalidation | Retain it as historical evidence; do not execute or present it as the current answer. |
| Delivery acknowledgement is lost | Retry the same logical delivery intent; preserve uncertainty where the receiver cannot deduplicate. |

## Correctness and failure boundaries

1. A duplicate delivery cannot create a new logical delegation or accepted action
   intent under the same scoped identity. Reusing an identity with different
   content is an error.
2. A result for revision A cannot authorize an action for revision B. The revision
   and authorization checks and intent record occur in one case-authority
   transaction or equivalent atomic conditional operation.
3. That accepted intent is the commitment point. A subsequent revision requests
   cancellation according to Project 1's contract; it does not retroactively undo
   an intent or guarantee that an already dispatched external request stops.
4. No specialist possesses booking-mutation authority. The coordinator returns
   evidence to the case authority; execution follows Project 1's effect contract.
5. Local cancellation does not prove that a remote model stopped. Invalidation
   prevents late results from influencing current actions even when remote work
   cannot be cancelled.
6. Process recovery comes from the execution adapter's persisted records and
   stable identities, not the lifetime of a Python task or HTTP connection.
7. Expired work and invalidated results cannot silently become current after
   reconnect, handoff, retry, or a delayed result callback.
8. Before cleanup exists, define result/replay horizons and retained delegation,
   result and effect tombstones. Deadline expiry or display-history pruning cannot
   permit duplicate acceptance or erase reconciliation evidence. A late replay
   after pruning must deduplicate or receive a documented expired-identity error.
9. Accepted useful work can make progress within declared limits. A system that
   rejects every result does not satisfy stale-result safety.
10. Voice interruption affects speech through native LiveKit behavior. It changes
   specialist work only when an explicit cancellation policy applies.

### Source binding, provenance and factual evaluation

At acceptance, bind the immutable bounded context to a trusted input fingerprint
and scoped evidence references with immutable content digests/versions, including
the supplied policy version. Resolve only authorized sources through the evidence
adapter; neither a mutable URL nor a specialist-supplied digest can replace the
accepted bytes. Bound reference counts, reference sizes and cited regions/rules;
reject arbitrary fetch URLs, inaccessible sources and mismatched fingerprints.
A source change requires a new accepted logical request under the identity policy.

Results retain request/revision, result-schema version, accepted input fingerprint,
bounded supporting evidence references, uncertainty and producer/attempt provenance.
Record the selected model/version/configuration where applicable, and label
unavailable provider metadata honestly. Provenance records how an answer was
produced; it proves neither factual correctness nor action authority. A reported
completion timestamp is diagnostic data. The execution/case authorities use their
own observed time and existing protected deadline contract; model timestamps
cannot revive expired or invalidated work.

P3-11/P3-15 and P3-I03/I04/I16/I17 distinguish structural validation from factual
evaluation. Known fixtures must catch valid JSON containing incorrect extracted
values, invented policy rules, another input's evidence or another account's source.
Missing, contradictory or ambiguous source facts require clarification or explicit
independent verification before consequential use; confidence alone is insufficient.
Test adversarial source text as inert data and retain positive examples whose
correctly grounded current result can progress through separate exact authorization.
These fixture outcomes do not certify arbitrary model factual accuracy.

### Commit-time applicability schedule

For P3-06/P3-I12, use barriers against the actual PostgreSQL case authority:
receive and validate a current A result, prepare its intent, let a separate
transaction commit revision B, then attempt A's intent commitment. Assert atomic
rejection, zero current action intents/effects derived from A, and one successful
independently confirmed current B path. Also exercise the inverse ordering and
P3-07's revision-after-commit boundary; a later revision cannot retroactively undo
an accepted external intent. Rechecking a mock, rejecting every result or relying
on a fortunate sleep schedule cannot satisfy this gate.

### Performance evidence

Measure all three baselines using equivalent inputs and identify unavoidable
differences in context construction and orchestration. Collect first audible
response, first meaningful response, time to useful specialist result, dispatch
delay, queue age, cancellation acknowledgement and invalidation time, event-loop
lag, CPU/RSS, model usage, and errors. Filler speech is not a meaningful result.

For controlled stale-result scenarios, require zero stale action intents accepted
and verify that expected current results are accepted. Report rejection counts
against known injected cases; a higher rejection percentage is not inherently
better. Report sample counts and distributions, workload and resource limits,
provider/model versions, regions, and cost. Offline task throughput does not
establish real-media or model capacity. Set regression budgets from a recorded
baseline before the benchmark gate; do not advertise unconditional latency bounds
across independent model providers.

## Acceptance matrix

Every case needs an automated assertion and a retained diagnostic artifact.
Deterministic adapters control model outcomes, clocks, scheduling, and failpoints;
fixed sleeps do not establish race correctness.

| ID | Required scenario and assertion |
| --- | --- |
| P3-01 | A valid current request completes through the Python-to-TypeScript contract, delivers a useful structured result, and permits an explicitly authorized fake action. |
| P3-02 | Hold the specialist on a test barrier while the user asks another question; the conversational agent responds without waiting for specialist completion. |
| P3-03 | Submit the same scoped ID concurrently; obtain one logical delegation. A changed payload under that ID produces a conflict. |
| P3-04 | Deliver the same completion repeatedly, including after a restart; record one accepted logical result and one action intent. |
| P3-05 | Revise A to B while A runs; complete A afterward. Record A as outdated and accept zero actions for B based on A. A valid B result still progresses. |
| P3-06 | Interleave revision update with result validation and intent acceptance using barriers. Only the operation allowed by the atomic case-authority contract commits. |
| P3-07 | Revise after intent commitment but before external execution; demonstrate the documented cancellation boundary and visible outcome, without claiming unconditional reversal. |
| P3-08 | Kill a specialist or coordinator process at a controlled failpoint; recover eligible work through the persisted execution adapter without losing accepted work or duplicating an authorized effect. |
| P3-09 | Expire the deadline before dispatch and during work. No new attempt starts after the execution contract forbids it; late results remain inapplicable. |
| P3-10 | Request cancellation; let the specialist ignore it and return. Report the observed remote outcome separately and accept no action from the invalidated result. |
| P3-11 | Send malformed output, wrong revision, unsupported schema, mismatched tenant, or oversized context/image/result. Reject safely and preserve an explanation. |
| P3-12 | Disconnect the room or hand off while work runs. Deliver through the stable route into the correct returning interaction without leaking another account's context. |
| P3-13 | Saturate one tenant's cap; prove global and per-tenant bounds, documented overload responses, and progress for another admitted tenant. |
| P3-14 | Stop and restart containers with the same persistent volumes. Restore accepted delegation/result state; replay a callback safely. |
| P3-15 | Run static screenshot and fixed-policy fixtures with missing, ambiguous, and adversarial text. Require schema-valid evidence or clarification; no specialist mutation capability is available. |
| P3-16 | Compare tools, a native local subagent, and a remote specialist under the same scenario, models, prompts where applicable, and load. Retain raw timings, outcome correctness, cost, and configuration. |
| P3-17 | Run the integrated browser against actual self-hosted LiveKit; observe voice responsiveness, interruption, and result routing. Label fake inference separately from live-provider evidence. |

## Development checkpoints

| Checkpoint | Deliverable before proceeding |
| --- | --- |
| D1 Contract | Retained tools/native-subagent baseline and remote-boundary decision first; then one authenticated bounded capability, P1-owned attempt observations, schema/scope fixtures, limits and narrow local ports. |
| D2 Reliability | Persisted execution adapter, duplicate handling, revision fencing, cancellation/invalidation, and deterministic crash cases. |
| D3 Multimodal example | Static screenshot extraction and the second policy capability; uncertainty and evidence handling; read-only specialist permissions. |
| D4 LiveKit integration | Actual browser session, native local baseline, independent specialist, current result delivery after handoff/reconnect. |
| D5 Evidence | Baseline comparison, local load and saturation run, all required acceptance tests, reproducible demo, API review, and failure-contract documentation. |

Before the first remote implementation slice, retain the controlled tools/native
subagent baseline and a decision explaining the process/language or recovery
boundary. The first remote slice is one capability with a scripted TypeScript
handler and a Python coordinator. It must demonstrate a valid result, one delayed
result made stale by a revision, and the same-ID conflict before adding models or
the second specialist.

## Release gates

The project work area must include `AGENTS.md` with safe commands and ownership,
`Design.md` with data flow and failure boundaries, and `README.md` with setup,
public contract examples, mode selection, and acceptance-ID references. Its code
harness must expose the P3 scenarios through the shared runner, return structured
outcomes and artifacts, and keep missing implementations explicitly pending.
When a real second consumer establishes a package boundary, build the applicable
wheel/npm-pack artifacts and execute the minimal public-API example from an
isolated installed consumer with declared dependencies and exports. Repeat at
release; no sibling source path or full sibling service deployment is implicit.
An AI coding agent must be able to locate the contract, execute a bounded scenario,
and diagnose its result without inferring commands or treating skipped work as
passing evidence.

Local-ready V1 requires all deterministic correctness, process-recovery,
cross-language, fixture, and self-hosted LiveKit integration tests above to pass
through documented local setup. The shared `offline`, `lab`, and `live` modes
separate deterministic execution, actual local media integration, and external
inference; initial image/model downloads are setup steps. No Cloud account, real
carrier, or paid inference is required for local-ready evidence.

Portfolio-ready V1 additionally requires selected live-model screenshot/policy and
voice runs with outcomes checked, published configuration and costs, three
baseline measurements, a short success-and-failure demonstration, a minimal API
example, and an independently reviewed failure contract. Live-provider credentials
are optional for running the local suite, but the live claims require retained
live evidence. The implementation must be explainable and modifiable by its author;
record assistance accurately.

## Deferred scope

Live video and continuous screen analysis, additional specialist roles, dynamic
agent discovery, arbitrary DAGs, agent marketplaces, protocol-standard claims,
general-purpose orchestration, custom media transport, real supplier mutations,
payments, priority scheduling, Kubernetes, multi-region failover, and production
scale claims are outside V1. A second inference-provider configuration and Cloud
simulations are optional compatibility/evaluation work, with their evidence
separate from local acceptance. Changes to these boundaries require an explicit
scope revision with acceptance criteria and an estimate before implementation.

## References

Use the native patterns as integration points and performance baselines. See
[workflow patterns](https://docs.livekit.io/agents/logic/workflows/) and
[background subagent delegation](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/).
