# Delegation Reliability Python package

Status: Active
Last reviewed: 13 November 2026

## Overview

A typed Python coordinator, issued-result runner, explicit delivery/confirmation
composition and bounded projection/processing/applicability clients over public P1
authority. A controlled native SDK comparison remains available as a separate
provider-free baseline; the installed consumer journey is described below.

## Implementation status

P3-A implements the focused native baseline. The contracts/security modules add
strict policy wire, local principal/evidence checks and finite ephemeral permits.
P3-I05's TypeScript package implements the scripted HTTP specialist. P3-I06 adds
this package's Python SpecialistClient and DelegationCoordinator submit/find/get/
cancel API through P1's public opt-in read-only accepted-work profile.

P1 atomically owns complete immutable accepted bytes and their computed digest.
The version-1 acceptance profile issues no attempt. I07A adds DelegationRunner
through P1's separately owner-upgraded version-2 public ExecutionPort: explicit
issued invocation, strict grounded result validation and P1-owned durable bytes.
The accepted wire attempt remains proposed metadata. I07B adds explicit result
delivery and exact-confirmation authorization through public P1 v3 ports, with an
exact case-control read and cooperating persisted local receiver. I08 adds the
public composition/inspection example and registered lab P3-01/P3-03/P3-11 runners.
Fourteen complete P3 product cases remain planned.
Broader workloads, autonomous scheduling and real models remain later slices.
I16 adds the separate read-only document HTTP path described below.


### Origin-bound policy API

Explicit `ChannelPolicyRequest` and `ChannelPolicyResult` wrap the unchanged
fixed-policy-v2 contract with input/result version 3. The six-field origin retains
the P2 profile, original operation, input receipt, SHA256 and canonical UTF-8 byte
length. Public parse/produce/encode functions validate both fingerprints and the
complete wrapper bounds. No raw channel message belongs in P1 policy input.

`ChannelPolicyCoordinator.submit` preserves exact logical matching;
`accept` explicitly returns the first equal-origin winner without renewing its
deadline or evidence. Both preserve original attempt bytes, and newly created
work must exactly match the submitted envelope. Its read-only `scope` property
is configured identity, not a live authorization observation.
`ChannelPolicyRunner` adapts issued version-3 history to the existing
`FixedPolicyInvocationPort`, verifies the inner result and wraps it back into
version 3. `ChannelPolicyDeliveryClient` and `ChannelPolicyResultReadPort` retain
the complete outer result bytes for delivery. Legacy public defaults stay v1/v2.

The application supplies all credential-bound ports, immutable evidence and finite
routes. These facades create no queue, worker, native room, migration or provider
composition. The [origin-bound work item](../../../docs/work-items/0044-origin-bound-channel-policy.md)
records unit/socket checks, fourteen actual source assertions and isolated
package qualification with 41 origin fake-port tests. Installed actual repetition
and the joined native/media journey remain separate later evidence.

## Standalone installed consumer

The maintained `make p3-package-check` command builds a fresh declared P1 dependency
wheel, P3 wheel/source archive/rebuilt wheel and specialist npm archive. It checks
exact payloads, raw package guides, wheel RECORD/dependencies, installed public
imports and strict consumers, then executes the native baseline and shipped HTTP
example outside the checkout. The default eight assertions need cached frozen
build dependencies and no database, room or provider configuration.

Use `.venv/bin/python local-setup/scripts/p3_package_check.py --lab --report
.local/validation/p3-package/<fresh-name>.json` for the explicitly configured local
lab. This repeats the eight offline assertions and adds eight lab assertions; the
sixteen total are not sixteen PostgreSQL scenarios. The selected host is macOS
arm64 with Python 3.14.10 and Node 24.22.2. Other platforms and a published release
remain separate qualification work.

`examples/standalone_policy.py` composes configured public ports and actually calls
`policy_completion.run_completion`. The application supplies immutable evidence,
finite case/receiver mappings and a separate exact operator Confirmation. Import
starts no listener, migration or worker. Successful configuration transfers client
ownership to the application; close attempts independent owners, preserves the first
failure and retains cleanup after caller abandonment. Owner installation and the
synthetic leased worker remain separately labelled test tooling.

The lab uses actual P1 work/case authority, the installed scripted HTTP specialist,
a cooperating SQLite receiver and one leased synthetic supplier effect. A caller
process is killed after known completion; a fresh process replays the original
owner, request and commands. Lookup reads are allowed, while new issue/completion/
authorization writes, specialist invocation, receiver acceptance and supplier apply
must remain zero. Cancellation preserves the original result, delivery/action
receipts and terminal ACK; a separate refresh records invalidation without new
permission. Three bounded proofs join exact identities and a complete retained-file
index binds nested summaries and captures. This is local synthetic qualification,
not P2 integration, remote models, human acknowledgement or a full charter release.
The [current handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md) records exact outcomes and remaining work.

## Bounded document HTTP

I16 adds the read-only booking.extract_document capability beside the existing
policy wire. Python exposes DocumentSpecialistClient and separate document request/
result codecs; TypeScript exposes the public document module, DocumentHandler and
configured scripted provider. The examples document_extraction.py and
document-http.mjs accept explicit clients/requests. Import loads no source image,
model, listener or credentials; the application owns configured evidence and clients.

One scoped immutable PNG supplies four ordered fields: booking reference, property,
check-in and check-out. Known values carry exact source/region witnesses; missing
and ambiguous values require clarification. Structural validity and exact correlation
are checked separately from the independent synthetic-image factual oracle.
Image text remains inert data. The finite scripted mapping is not OCR or general
vision inference, and no mutation/notification permission comes from its output.

Actual PNG bytes are checked before provider entry: at most 2 MiB and 2048×2048,
RGB8/RGBA8 noninterlaced, bounded framing/CRC/zlib/scanline/filter checks. Unsupported
formats, animation/ancillary chunks, truncation and trailing data fail closed.
The fixed worker runs without inherited environment or caller-selected code; normal
results require actual exit 0. Direct handler calls, workers, sockets and provider
promises retain finite ownership through timeout/cancel and incomplete shutdown.
A fresh original deadline is checked after decoding before provider work; retrying
public close observes remaining owners rather than assuming remote cancellation.

Use `.venv/bin/python local-setup/scripts/p3_document_check.py --plan` to inspect
the closed twenty-case inventory. The source command uses actual local Python/Node
HTTP; `--installed` rebuilds fresh artifacts, repeats the maintained offline package
assertions and reruns the same twenty image cases outside the checkout. These are
socket/contract/fixture checks, not twenty PostgreSQL or real-model scenarios.
The selected host remains Python 3.14.10 and Node 24.22.2 on macOS arm64.

P1's public work operation remains policy-only. Image HTTP is not durable image
acceptance, issued execution, projection, delivery, confirmation or action. A reviewed
versioned P1 operation extension is required before that integration. See the
[current image handoff](../../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
for qualification, provenance and remaining gates. The I17 path below has its own
versioned HTTP contract; full charter/release qualification remains separate.

## Versioned fixed-policy HTTP

Python exposes `FixedPolicyRequest`/`FixedPolicyResult` and strict parse/produce/
encode functions in `delegation_reliability.fixed_policy_contracts`. Configure
`FixedPolicySpecialistClient` and call `verify_fixed_policy_facts` from
`delegation_reliability.fixed_policy`, or pass those configured ports to
`examples/fixed_policy_evaluation.py`. A transport-correlated result still needs
that explicit factual check against the supplied evidence records.

I17 implements an explicit input/result version 2 for booking.evaluate_policy.
Version-1 canonical bytes and public defaults stay unchanged. The new typed path
accepts two scoped immutable JSON sources: a notice_v1 policy declaring only
notice_minimum_days with threshold seven, and zero to two identified notice-day
observations. Source reference versions remain independent of the semantic policy
version. All exact source bytes, digests, scope and complete fact witnesses must
match; two agreeing observations are usable, missing or conflicting observations
require clarification, and invented rules or values fail factual verification.
Policy, fact and image text remains data and grants no tool or mutation permission.

Shape/correlation validation and factual verification are separate. Factual checks
also run on expired results, so lateness cannot hide unsupported answers. The fixed
handler is a deterministic evaluator of this one declared rule, without a model,
provider call, generic policy interpreter or new worker. The configured public
examples receive explicit requests, evidence and clients; importing them performs
no setup. Client metrics describe owned transport calls and validated correlations,
not factual truth or business permission. Timeout/cancel retains actual I/O until
settlement; incomplete close and later close retry remain explicit.

Use `make p3-fixed-policy-plan` for the twenty-case inventory,
`make p3-fixed-policy-check` for the source contract/loopback journey and
`make p3-fixed-policy-package-check` for the same journey using fresh installed
artifacts. Installed mode separately repeats eight offline package assertions;
twenty is not a PostgreSQL or model-inference count. The declared source/installed
budgets are 120/360 seconds including twenty cleanup seconds, with at most 32
owned child processes, 64 KiB per captured stream, 2 MiB aggregate capture and
32 KiB per proof/report. The selected host is macOS arm64, Python 3.14.10 and
Node 24.22.2. Source, installed and affected compatibility results and retained
failure provenance are recorded in the [fixed-policy handoff](../../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).

The original DelegationCoordinator and DelegationRunner retain version-1 defaults.
Explicit FixedPolicyCoordinator and FixedPolicyRunner now compose policy version 2
through the same public P1 work/execution ports and shared typed ownership cores.
P1 accepts opaque policy-operation bytes; P3 verifies their versioned facts. This
I18A implementation and its selected qualification are recorded in the [handoff](../../../docs/work-items/0041-standalone-channel-and-durable-policy.md).
Projection, refresh and action remain version-1-only. Explicit policy-v2 result
delivery is implemented under the [result-return work item](../../../docs/work-items/0043-stable-result-delivery-and-return-context.md), with selected source delivery/read qualification passed. Original P2-input binding
and joined native voice/SMS qualification remain separate. I18B adds the explicit native
application described below; fourteen full charter rows and broader integrated
release remain planned.

### Opt-in durable policy version 2

Construct FixedPolicyCoordinator with a public authenticated TaskExecutionPort and
trusted CaseAuthorityPort. Submit acknowledges the original immutable request
through P1 before an explicit FixedPolicyRunner.run_once(work_id, command_id).
The runner requires the original logical owner plus exactly two immutable scoped
JSON EvidenceRecord values, at most 4096 bytes each. Only a newly issued current
grant permits HTTP invocation. Replaying its original command never grants a new
invocation; known results preserve their original bytes and commit disposition.

FixedPolicySpecialistClient.invoke_observed(request, evidence=records) in Python
and invokeObserved(request, records) in TypeScript copy and validate that exact
pair before I/O, then verify every fact and witness even on a late result. They
return the typed result, observation time and separate candidate, clarification or
expired classification. The existing invoke method remains the correlation-only
transport API. The durable runner independently checks facts before P1 completion
and stored-result inspection; P1 eligibility uses fresh authority time and stays
separate from semantic validity and current case applicability. Missing/conflicting
facts clarify. Cancellation does not erase previously eligible result truth.

The configured Python example examples/durable_fixed_policy.py and TypeScript
observeFixedPolicy export receive explicit public clients, evidence and identities.
They perform no implicit DDL, provider setup or scheduling. Close independent
owners within a tier, await successful facade closure, then close shared case
readers; incomplete close retains actual I/O and may be retried.

Use make p3-fixed-work-plan, make p3-fixed-work-check and
make p3-fixed-work-package-check for the declared twelve-assertion source/installed
journey. Installed mode separately repeats eight offline package assertions.
The selected bounds are 180/360 seconds including twenty cleanup seconds,
at most 32 owned children, 64 KiB per stream, 2 MiB aggregate capture and 32 KiB
per proof/report. The synthetic local profile creates thirteen issued attempts,
retains eight valid results and rejects five invalid bodies, with one owned
postcommit kill, fresh-process original lookup and independent scoped authority
proofs. The linked handoff records measured outcomes, prerequisites and retained
failure provenance for these assertions. No new P1 storage
version, supplier call, result action or native/session owner is introduced.

### Fixed-policy result delivery

Construct FixedPolicyDeliveryClient with a FixedPolicyResultReadPort, public P1
DeliveryPort, structural ResultReceiverPort, trusted Scope, exactly two immutable
EvidenceRecord values and DeliveryBinding entries. Defaults remain two active
calls, a five-second caller budget and one-second cleanup observation. Imports
start no listener, migration, worker or implicit retry.

The facade independently validates original accepted/issued/result bytes and both
source witnesses. A new delivery requires candidate applicability and eligible
P1 begin; missing or conflicting policy facts cannot be promoted by a forged
candidate label. An original possible delivery performs receiver find only.
A missing lookup remains unknown and does not grant another accept. A receiver
receipt retains the original result digest; an SMS notice digest is different.

The client owns and closes its delivery/receiver ports. The application keeps the
shared result inspector and closes it only after delivery actually drains.
Cancellation stops waiting without business cancellation. Incomplete close retains
owners for an explicit retry. Receiver acceptance, carrier delivery, playback,
human acknowledgement and guarded booking action remain separate. Current case
applicability is observed across separate reads and is not an atomic case fence
across an external receiver commit. The existing v1 delivery/action APIs stay compatible.

The selected source result-return gate passed sixteen storage and four return
assertions with three real P1 results, two P2 receipts and no carrier/provider
calls. Its specialist port is explicitly scripted; native-grant reads use no RTC
room. The separate fresh package gate checks installed public ports and twenty
unchanged fake-port tests. It requires its own passing report; source execution
does not substitute for an installed consumer.

### Opt-in native background policy

NativePolicyApplication and NativePolicyAgent compose the explicit policy-v2
facades with one supplied AgentSession. Trusted setup freezes one positive-revision
request, original command and exactly two immutable JSON sources. Configure the
runner with two slots for one run and one concurrent read; its default remains one.
The model receives no scope, case, command or evidence-selection arguments.

The tool acknowledges through P1 before its silent ctx.update releases the SDK
foreground. One retained run_once task is shielded from the SDK waiter. SDK
cancellation means stopped waiting, never business cancellation. Admission remains
reserved until that task and the public facade pending counts actually settle;
a timed-out wrapper alone cannot free the slot. Repeated calls inspect the original
work rather than issue another command. Close preserves actual owners and may
report cleanup_incomplete until a later explicit retry observes settlement.

NativePolicyObservation exposes a copied closed JSON value of at most 4,096 UTF-8
bytes. It separates original result/disposition from as-of applicability and labels
application read completion time. No-work requires an actual original-key read;
unknown reads never invent fresh authority fields. Missing/conflicting facts retain
null eligibility and full witnesses. The card cannot authorize an action, and the
DTO supplies no invented current-case revision or case-observation timestamp.

The configured examples/native_fixed_policy.py function accepts an already supplied
session, application, room and exact browser participant. Its first profile is RTC
text with one SDK input owner and audio input/output disabled. The lab host owns
fixed authenticated session/observation routes and separate in-memory operator
capability; an RTC token grants no privileged read. The [native-policy handoff](../../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records implementation and selected qualification. SDK-local unit results do not
establish PostgreSQL, RTC/browser, audio, model-quality or full-release evidence.
No P2 runtime, new queue/schema, autonomous retry or v2 action/delivery adapter is
introduced.

## Documentation

- [Project guide](../README.md)
- [Project design](../Design.md)
- [P3 charter](../../../docs/projects/delegation-reliability-scope.md)
- [Baseline work item](../../../docs/work-items/0023-p3-native-baseline.md)

## Requirements

Use Python 3.14 with the frozen root workspace development environment and the
pinned livekit-agents 1.8.11 dependency. The package declares the matching public
agent-continuity[postgres] dependency for acceptance; its HTTP client uses the
standard library without an implicit/transitive HTTP dependency. No Docker, room,
model download or provider credentials are needed for the native baseline and
unit/socket tests. Real acceptance additionally needs the explicitly owner-installed
P1 read-only work profile on local PostgreSQL; importing a client performs no DDL. The TaskGroup API comes from the SDK beta.workflows module;
this exact pinned API is exercised, not claimed generally stable across releases.

## Commands

From the repository root after its documented frozen development bootstrap:

```sh
.venv/bin/python -m delegation_reliability
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_*.py' -v
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

The example prints one safe JSON report. Redirect it to an ignored local evidence
file when retaining an experiment; it contains fingerprints and finite outcomes,
not the submitted note or full conversation.

## Validation

Require identical input/result fingerprints, no completed result while held, a
useful read-only explanation before release, a real SDK-observed final result,
native task/group completion and bounded cleanup. Invalid/oversized inputs fail
before session creation. Tests also cover timeout, caller cancellation and safe
error/log behavior. These are orchestration observations, not model quality,
physical audio, durable acceptance, authenticated case authority or process
recovery. Individual timings are host observations, not benchmark percentiles.

## Acceptance and client APIs

Use declared exports from delegation_reliability or the documented coordinator,
case_adapter, runner, completion, delivery_contract, action_adapter, http_client and contracts modules. Application startup supplies a
credential-bound P1 TaskExecutionPort, trusted Scope and CaseAuthorityPort to
DelegationCoordinator. submit snapshots a strict DelegationRequest; find uses its
logical ID, while get/cancel use the returned P1 work ID and a stable cancel command.
Exact semantic replay returns the original bytes/deadline, allowing only attempt
transport metadata to differ. Changed input conflicts. An ambiguous acceptance
acknowledgement is reconciled by original-key read, without a second submission.

ManagedCaseAuthority adapts the public P1 managed-case projection using at most
128 trusted CaseBinding values. It cannot know cancellation after a committed
intent from that projection, so committed cases fail closed with
case_state_unavailable. Ordinary uncommitted cases can progress. A preflight read
cannot grant atomic current-case or mutation authority. The application owns the
case client; the coordinator owns/closes its injected work client. The coordinator
never injects ResultDeliveryPort; I07B's separate completion facade implements it.
ExactManagedCaseAuthority uses public case_control_api and trusted ActionBinding
values to observe exact cancellation even after commitment. Its authenticated
identity includes actor, scope and schema; no request payload selects authority.

SpecialistClient(SpecialistEndpoint(port), authorization) supports async invoke,
status, cancel, invoke_observed and close. It connects only to literal 127.0.0.1, one POST/socket,
without ambient proxies, redirects or retries. Defaults are four active calls,
five seconds total and one second cleanup observation; validated overrides remain
finite. Responses require exact bounded framing and typed schema/correlation.
A validated candidate still needs trusted source facts and current case/action
checks. Timeout or cancel does not prove remote computation stopped.

Both libraries retain owned work until actual settlement after waiter cancellation
or timeout. No waiting queue or timer frees a live slot. Finite close reports
cleanup_incomplete when held work remains; retry close after actual settlement.
HTTP metrics distinguish framed received from validated public observations.
Named logger events use only fixed operation/code/outcome values; handler setup,
execution/flush budgets and export remain application responsibilities.

## Issued runner API

Application startup supplies a public P1 ExecutionPort already bound to verified
WorkScope and an explicitly upgraded v2 profile. DelegationRunner(executions=...,
scope=..., owner_id=..., specialist=..., case_authority=..., evidence=...) owns and
closes both execution and specialist clients. The application owns the case-read
adapter. Evidence is defensively copied, at most four verified records and 16 KiB.
Defaults are one active runner call, five seconds of caller observation and one
second of cleanup observation; configured active calls stay at most four. P1's
default ten-second logical lease and at most three issued attempts remain authority
policy; actual retained HTTP threads/streams have their own finite occupancy.

run_once(work_id, command_id) issues one stable command. It never invokes a replayed
or ambiguously acknowledged issuance. Before physical HTTP it observes the same
current uncancelled running permit and checks local abandonment/expiry. This is
an eligibility observation, not a physical execution fence. The wire ID is attempt_
plus the issued UUID's 32 hexadecimal characters, preserving the accepted payload.
A timed-out/canceled caller does not free its owned task or prove remote stop;
late known results may still be retained as history. No later HTTP can start when
that caller abandoned issuance.

The returned DelegationRun separates invoked, recorded result and current view.
inspect(work_id) reads the original accepted input and current P1 attempt/result,
then returns fresh read-only applicability. A superseded recorded result can differ
from that current view. P1's public result(work_id, attempt_id) keeps old result
history inspectable. The runner itself accepts no action or delivery. Case-read failure
returns unavailable, and a revision change returns outdated while retaining the
computation. Both are read observations, not atomic current-at-commit decisions.

SpecialistClient.invoke remains strict candidate-only. invoke_observed returns a
SpecialistResultObservation with candidate/expired timeliness under the same strict
framing, identity and total transport budget, enabling historical result retention.
P3 independently checks evidence and factual eligibility before storing even late
bytes. P1 decides its own time/lease/cancellation disposition from database time.

The actual gate is make p3-execution-check after documented local restricted-role
PostgreSQL setup. It explicitly installs v1, seeds input, owner-upgrades v2 and
uses actual TypeScript sockets; only the case-read preflight is synthetic. Owner
credentials never enter runtime children. Package verification and complete
recovery/media/action/delivery acceptance remain separate gates.

## Explicit completion APIs

DelegationDeliveryClient(results=..., deliveries=..., receiver=..., scope=...,
evidence=..., bindings=(DeliveryBinding(case_id, conversation_id, recipient_id),))
implements ResultDeliveryPort. deliver_once(work_id) returns DelegationDelivery
with independent missing/prepared/unknown/accepted state, the immutable P1 snapshot
and whether this call invoked the receiver. inspect(work_id) reads the current
P1 delivery snapshot without receiver I/O; deliver_once reconciles possible sends. Only newly created P1 begin permits accept;
an existing possible send uses receiver.find and absence stays unknown.

DelegationAuthorizer(results=..., actions=..., scope=..., evidence=...,
bindings=(ActionBinding(case_id, task_id, authority_case_id, authority_actor_id,
authority_scope_id, case_schema),)) exposes authorize_once(work_id,
confirmation=..., command_id=...) and inspect(work_id). Confirmation must be the
separate exact public P1 Confirmation, explicit=True, for the original result's
trusted task/case/revision and quote. Current work/result eligibility and case
intent commitment use P1's atomic ActionPort guard; a prior case read cannot
replace it. The returned DelegationAuthorization contains the stable action
receipt and reconciled flag. No supplier I/O happens in this facade.

Both facades default to two active calls, five-second caller observation and
one-second cleanup observation. They own their delivery/action P1 client; delivery
also owns its receiver. The application owns the shared results inspector and
case client. Inputs and nested returned values are defensively reconstructed before
awaiting. A canceled/timed-out waiter retains actual owned work until settlement;
close reports cleanup_incomplete if it remains held. Ambiguous acknowledgements
read only the original identity; lookup failure preserves acknowledgement_unknown.
Known original receipts remain facts after later cancellation, expiry or revision.
Fixed delegation_completion log events and numeric process-local counters contain
no submitted input, identifiers, secrets or raw dependency exceptions.

make p3-completion-check runs thirteen actual isolated PostgreSQL/HTTP cases with
case v4 and work v3, distinct owner/runtime credentials, a cooperating SQLite
receiver, fresh-process reads, receiver commit ACK loss/SIGKILL and one actual
leased fake supplier effect. The trusted original inquiry supports a public-only
ABA revision schedule: original2 becomes stale after alternate3/original4; no
private quote injection or revision offset is used. Exact confirmation remains a
separate synthetic operator input. This does not qualify voice, models, P2 routing,
autonomous recovery or complete charter cases.

## Public composition and inspection example

The standalone [policy completion example](../examples/policy_completion.py)
imports only declared public APIs. Supply a strict DelegationRequest, two configured
DelegationCoordinator clients, DelegationRunner, ResultDeliveryPort,
DelegationAuthorizer and separate exact Confirmation to run_completion. Explicit
execution/confirmation command IDs keep replays bound to original identities.
Concurrent equal submission may return one created acceptance or original replays;
changed input still conflicts through the coordinator. The example does not create
schemas, a receiver, background workers or inference clients, and the application
owns every supplied client's close lifecycle.

inspect_accepted(work_id, coordinator=..., runner=..., delivery=...,
authorizer=...) returns distinct accepted, execution, delivery and action snapshots
without invoking, delivering or authorizing. run_completion copies request and
exact confirmation before awaiting, retains human acknowledgement as unobserved,
and returns safe identity/digest/state fields. Passing an invalid or non-explicit
confirmation fails without deriving consent from the specialist answer.

The registered P3-03 lab runner separately proves actual concurrent admission under
independently observed PostgreSQL lock contention and fresh scope-safe reads. The
registered P3-11 runner executes all bounded malformed/version/revision/tenant and
context/image/result rejections, with five actual invalid issued HTTP results,
zero invalid commits and later useful progress. Image decoding/extraction remains
future work.

## Versioned result projection

Explicit owner setup uses continuity_lab.work_admin.upgrade_work_schema_v4 and
projection_admin.install_projection_schema(owner_settings, binding=ProjectionBinding(
source_id, WorkScope(tenant_id, account_id)), limits=ProjectionLimits(max_records=3000)).
Serving receives only existing runtime settings, WorkDirectory and BearerToken.
open_result_feed_client supplies the immutable source_id; open_projection_client
binds that source and authenticated scope. Owner setup is a separate command and
runtime never creates or repairs a schema. A repeated exact install validates and
preserves rows; changed limits/source/scope fail rather than silently rebind.

ProjectionProjector(events=feed, executions=execution_client, projections=projection_client,
scope=scope, evidence=records, case_authority=exact_case_adapter) owns the three
clients. The application owns the shared case adapter and the projector's close
lifecycle. await project_once(limit=4) consumes at most eight contiguous source
references, then stops. checkpoint() and get(work_id=..., attempt_id=...) on the
projection client are read-only. The [public example](../examples/result_projection.py)
composes those calls without DDL, background tasks or inference.

Projection v1 stores at most 3,000 references by default, configurable 1–30,000.
Each canonical metadata value is bounded to 8 KiB, about 23.44 MiB raw at the
default cap, excluding indexes/WAL/backups. Source sequences use signed int64;
retention remains independently bounded. Reaching the cap raises capacity with
no checkpoint advance. There is no pruning/tombstone/automatic cap expansion in
this slice. Future retention policy cannot permit identity reuse.

Each schema_version=1/kind=result_projection row references exact source/event,
work/attempt/command and request/result digests. validated versus rejected is
separate from immutable applicability. The latter records as_of_non_atomic,
execution status/cancellation/current attempt, execution observation time, case
read availability/revision/cancellation/time and evaluation time. These are
separate reads. A case-only change creates no result-feed event and does not
rewrite a prior candidate. Current action permission always comes from P1's
atomic exact-confirmation guard. Foreign/unavailable case data is discarded and
represented by unavailable fields, never copied into diagnostics or storage.

Definite invalid P3 input/result/facts are quarantined with fixed rejection codes
and checkpointed; missing/changed source identities or unavailable execution
reads stop without advancing. Exact complete-batch replay retains original
metadata rather than reclassifying it. Partial overlap/moved checkpoints can
raise checkpoint_conflict; the application may explicitly schedule a fresh step.
An unknown write is looked up exactly once without another apply. If exact rows
are found, before/after describe the actually observed checkpoint; failed/absent
lookup retains acknowledgement_unknown.

Defaults are two active calls, five-second caller observation and one-second
cleanup observation, configurable within finite bounds. Timed-out/cancelled
waiters retain actual thread/port capacity until settlement. Abandoned pre-write
steps cannot later apply. close reports cleanup_incomplete while work remains.
Fixed result_projection operation/code/outcome logs and numeric metrics contain
no IDs, bodies, credentials or dependency text; telemetry failure cannot alter
stored truth. make p3-projection-check provides twelve actual isolated PG cases
and two owned-PID kills, separate from unit fake-port evidence. No source ACK,
autonomous delivery, scheduler, refresh policy, action or provider call is added.

## Delivery-only processing and terminal event ACKs

Owner setup calls projection_admin.upgrade_projection_schema_v2(owner_settings,
policy=CompletionPolicy(receiver_id, bindings)). Use up to 32 trusted DeliveryBinding
case/conversation/recipient mappings and one receiver UUID. Policy bytes are
bounded to 16 KiB and remain fixed across restart; a changed policy conflicts.
The upgrade preserves every v1 row/checkpoint/limit. Repeated v1 installation and
old public projection clients remain compatible with v2, including new result
writes. The tested versioned-profile row export/restore is separate from pg_dump.

open_processing_client(settings=runtime_settings, directory=..., token=...,
source_id=..., policy=...) opens an existing v2 profile. Public reads are
checkpoint() and acknowledgement(event_id=...). Bounded paging and ACK writes
are private to CompletionProcessor. The policy's metadata tables do not duplicate
P1 result bodies, delivery plans/receipts, action state or execution ownership.

CompletionProcessor(processing=client, source=feed, delivery=facade, results=reader,
scope=scope, evidence=records) owns processing/feed/delivery clients. The application
owns the shared result/case readers and the processor lifecycle. The additive
ProcessingDeliveryPort supplies copied scope/receiver_id/bindings; existing
ResultDeliveryPort consumers keep their original interface. The
[public example](../examples/result_processing.py) exposes process_results and
inspect_ack using declared imports without setup or implicit tasks.

process_once(limit=4) examines at most eight total references with at most one wrap.
The scan cursor permits later eligible work to pass unknown events, while the
terminal watermark advances only across contiguous terminal ACKs. Rejected content
and definitely historical not-required-as-of decisions are separate from accepted
receiver receipts. Exact source/event/work/attempt/request/result/projected-row
identity and fixed policy bind each acknowledgement. Same-case conversations
cannot exchange recipients. Processing does not call an authorizer or create
human confirmation. Receiver acceptance is not playback or human acknowledgement.

Known exact receipts precede current applicability checks. Possible send plus
receiver absence stays unknown even after cancellation/expiry/case changes and
gets no ACK. Unavailable case/delivery state is deferred; unavailable or changed
source state cannot be invented. The existing facade alone permits a new receiver
accept after P1 begin.created. No automatic retry, recipient rebase or event-derived
action occurs. I11 adds a separate explicit refresh/display policy. Source incarnation rotation
and broader action/recovery remain later work.

Each ACK and scan/control revision commit atomically in a coherent repeatable-read
snapshot. A concurrently appended projection remains outside that snapshot and is
visible on the next read. Definite serialization conflicts remain checkpoint_conflict;
ambiguous commits remain acknowledgement_unknown. Each can look up its exact
original ACK once without another write; failed/absent lookup preserves its code.
Original returned observations are defensively copied and cannot claim another
caller's advancement. Partial multi-event progress can remain committed after a
later event fails; public exact ACK/checkpoint reads expose those facts.

The v1 retained-record cap also bounds ACK count. ACK bytes are at most 4 KiB,
about 11.72 MiB raw at the default 3,000 records, in addition to at most 23.44 MiB
projection metadata. Indexes/WAL/backups are extra. Per-instance defaults are two
active processing calls, ten-second caller observation and one-second cleanup.
Blocking writes retain slots and owned exceptions through timeout/cancellation;
close reports incomplete until actual settlement. An abandoned read cannot start
a later ACK write. SQL/receiver work occurs outside conversational loops and no
external receiver I/O occurs under a P3 metadata lock.

Fixed result_projection operation/code/outcome logs omit submitted values and IDs.
Numeric processing counters report examined rows, terminal ACK observations,
unknown/unavailable observations and exact ACK reconciliations; they are local
observations rather than unique SQL row counts or exported metrics. Throwing
telemetry cannot change stored truth. make p3-processing-check runs sixteen actual
assertions with five owned-PID kills, immutable receipts and independent cleanup.
The [phase handoff](../../../docs/work-items/0033-outbound-replies-and-completion-processing.md)
records qualification limits. Full P3-04/P3-08 remain unregistered.

## Explicit refreshed applicability and retained display

Owner upgrade_projection_schema_v3 adds a fixed RefreshPolicy and refresh/display
metadata over an existing v2 profile. Use open_applicability_client with the
same explicit source/scope binding and policy. Serving never installs or upgrades
storage. Existing projection and processing clients remain compatible on v3.

ApplicabilityRefresher(events=feed, executions=execution, applicability=metadata,
scope=scope, evidence=records, case_authority=exact_case) owns the three injected
clients; the application owns the shared case reader. refresh observes exactly
one work/attempt under a stable UUID command and expected per-result revision.
Equal command replay is original historical fact, even after hide, cancellation
or current-source outage; it is not a fresh current-state read. Changed semantics
conflict. A new observation verifies exact source/event/attempt/request/result
identities, then separately observes current execution and case. The local CAS
orders metadata only, without atomic cross-authority or action permission.

Raw as_of_non_atomic fields remain distinct from effective classification and
retained invalidation witnesses. Candidate/clarification is not human consent.
Higher verified revisions, different-attempt witnesses and cancellation cannot
be erased by stale or unavailable reads. Host deadline expiry is explicitly
local/as-of. A postcommit grant-lease expiry does not invalidate the stored result.
Known P1/receiver receipts and processing ACKs remain original facts.

ApplicabilityClient.command and inspect preserve authenticated original facts.
hide_display is an idempotent permanent presentation tombstone, independent of
refresh revision. display returns that marker while original inspect/replay and
processing of hidden unknown events continue. No rows/identities are deleted,
expired or made new, and hide reclaims no capacity. Retention/replay lasts for the
profile lifetime. Default limits are 3000 total commands/four per result; maxima
are 30000/eight. Receipts are at most 4096 bytes. That default body allowance is
11.72 MiB before indexes/WAL/backups, not measured disk capacity or throughput.

The [public example](../examples/result_applicability.py) supplies refresh_result,
inspect_result and hide_result with no DDL, implicit scheduling, provider calls or
import-time I/O. Waiter timeout/cancellation retains actual tasks/threads until
settlement; close reports cleanup_incomplete while work is held. Ambiguous writes
and definite CAS/serialization conflicts reconcile one exact original identity,
without another write. Transient source failure is storage_unavailable; mismatched
immutable source data is invalid_source_state. Fixed result_projection operation/
code/outcome events and bounded local counters contain no bodies or credentials.

The [phase handoff](../../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
records the source-bound gate results, populated quiescent profile-row restore
and isolated installed consumer. That restore preserves the exact captured cut;
it does not claim recovery of a stale branch that omitted later authoritative
history. P1 runtime/schema and source-incarnation behavior are unchanged.

## Existing guarded action under races

The [configured public example](../examples/policy_completion.py) composes existing
credential-bound ports and exact caller confirmation, and inspect_accepted reads
accepted input, execution, result receiver and action facts without authorizing.
No new P3 or P1 runtime module/API/schema is required for I12. The explicit
make p3-action-races-check tooling schedules existing public action failpoints and
leased worker hooks in fresh synthetic authorities. Its sixteen selected assertions
cover both actual two-waiter SQL orders, stale A rejection/current separately
confirmed B progress, original A commitment/revision rejection, cancellation at
intent/claim/reservation boundaries, three owned process kills and fresh lookup
without another supplier apply. It preserves caller I/O after timeout/cancellation,
original command receipts, finite role-separated resources and exact independent
identity reconciliation. Each schedule has a fresh quote/supplier and its own
unchanged at-most-60-second work horizon. The 180-second gate budget is separate.

Read the [phase handoff](../../../docs/work-items/0035-send-policy-and-action-races.md)
for measured source and isolated installed-consumer results. This proof uses a
cooperating persistent synthetic supplier; an admitted noncooperating external
request remains uncertain. Display/applicability metadata never grants action
permission, exact confirmation never comes from result content and receiver
acceptance never establishes human acknowledgement. Full recovery/media and
remaining charter rows stay separate.

## Deadline/cancellation qualification

make p3-deadlines-check exercises existing public clients through eighteen selected
before/during-invocation schedules. Authority decisions use P1 database time after
admission. A deliberately noncooperating test-only Node peer can finish after
cancel/expiry; immutable late facts stay recorded and ineligible, regardless of a
claimed producer completion timestamp. The normal specialist remains unchanged.

Business cancel request, running non-durable remote ACK, lost ACK, recorded result,
as-of refresh and exact atomic action permission are independent facts. Waiter
abandonment retains real I/O and does not itself business-cancel; close remains
incomplete while held work exists. A successful result is not retroactively
invalidated by its old lease expiry. Fresh separately confirmed current work still
progresses through the configured public completion example with one fake effect.
Direct proof sidecars independently bind source/work/attempt/body digests, receiver
receipt and actual supplier calls. One post-late-commit process kill resumes by
lookup only. The [phase handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records measured qualification separately from offline fake-port checks.

## Explicit process recovery composition

The configured public [completion example](../examples/policy_completion.py) and
existing clients are sufficient for the selected I14 process-recovery composition;
no new runtime API, execution ledger, migration or import-time work is introduced.
The [phase handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
is the stable qualification and provenance reference. make p3-recovery-check runs
the explicit actual PostgreSQL/process fixture; source and installed qualification
are recorded there separately from offline tests.

Original accepted input, grant owner/command, immutable result and known receiver/
action receipts survive fresh Python processes. Replaying the original issuance
never invokes again. A distinct caller-supplied command may invoke only when P1
actually creates a current eligible attempt after observing the old lease expired.
An unresolved possible-send remains lookup-only; absence is not permission to retry.
Useful independent completion still receives its own exact receipt and processing
ACK. Separately supplied exact confirmation remains necessary for the atomic P1
action guard; the existing leased worker alone applies the fake effect.

Early read-only recovery uses an explicitly synthetic case preflight in a separate
account. Completion uses actual public P1 case/quote clients. The process fixture
retains directly joined source/request/result, Python/SQL backend, receiver and
supplier identities. Its Node journal is ephemeral observation, not durable work.
The selected bounds are seventeen assertions, eight verified kills, one SQL graph,
twenty-eight planned children and a 180-second total with fifteen for cleanup.
Diagnostics are bounded, body-free and never qualify. No result-derived consent,
automatic action/accept retry or physical exactly-once computation is claimed.

## Next milestone

I08 adds the first three complete registered P3 runners. I09/I10/I11 add explicit
projection, delivery-only processing and applicability refresh/display retention.
I12 validates selected protected action/revision/cancellation races through existing
authorities. I13 adds selected deadline/cancellation schedules without runtime changes.
I14 process recovery and I15 standalone composition have selected source/installed
qualification in their linked handoffs. I16 adds the bounded standalone image path;
I17 versioned fixed-policy HTTP and its qualification are described in the linked
handoff. The [I18A handoff](../../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records durable version 2 qualification. The separate I18B native application
and configured text example retain their own handoff and evidence scope. Fourteen
full charter rows remain planned and the project gate remains incomplete. Fake-port tests remain distinct from actual database/process evidence.
