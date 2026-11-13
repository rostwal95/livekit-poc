# Delegation specialist contracts and local HTTP

Status: Active
Last reviewed: 12 November 2026

## Overview

A TypeScript contract and authenticated loopback HTTP boundary for the read-only
booking.evaluate_policy capability and the standalone booking.extract_document
capability. It uses Node built-ins, explicit scripted providers and configured evidence. Importing the package starts no service and
reads no credentials. P1 remains the sole durable acceptance/issued-execution and
result owner through its separately installed public profiles.

## Implementation status

P3-I03/I04 provide strict request/result/error codecs, local bearer-digest grants,
scoped immutable evidence and finite live-attempt permits. P3-I05 adds the bounded
HTTP handler and typed client with focused actual-socket verification. Shared
review and release gates are recorded by the current work item. The Python I06
coordinator now owns immutable acceptance through P1's public work port; I07A's
one-step runner consumes P1-issued grants and records strict results through its
owner-upgraded v2 execution port. The HTTP service authenticates its own local
service principal and does not independently verify P1 issuance in this wire
version. Its ephemeral state never becomes a ledger or action authority. Durable
delivery/exact action are now composed by Python I07B through public P1 v3 ports,
without granting this specialist mutation permission. Autonomous recovery, real
models, media and complete P3 acceptance rows remain outside this HTTP slice.
I16 adds a separate typed document handler described below. P3-I08 now qualifies registered P3-01/P3-03/P3-11 lab runners;
fourteen P3 rows remain planned. Python I09 now projects P1 work v4 result
references into a separate versioned as-of metadata store. This changes no
TypeScript wire contract or service ownership, starts no scheduler and grants no
new specialist permission. Result bytes remain authoritative in P1. Python I10
adds explicit v2 processing metadata and terminal delivery ACKs with gap-aware
scan progress. Python I11 adds explicit refreshed applicability and display
tombstones in its own versioned metadata profile. These changes add no TypeScript
scheduler, send/action authority, wire change or remote-stop guarantee. The
[phase handoff](../../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
records the exact selected qualification.

Python I12 composes the existing public P1/P3 guarded-action path under real
revision/cancellation lock orders and process loss. The specialist remains a
read-only producer with no action, revision, retry or supplier permission. The
[action-race handoff](../../../docs/work-items/0035-send-policy-and-action-races.md)
records that selected validation separately from this unchanged TypeScript wire.

The dedicated tests/fixtures/deadline-peer.mjs is an intentionally noncooperating
I13 fault peer, separate from production SpecialistServer. It uses the public
specialist package and finite scope/evidence/attempt checks while allowing a held
read-only computation to finish after business cancellation/expiry. Its running
cancel ACK is non-durable; one cancel endpoint deliberately loses that ACK. Actual
result readiness is recorded separately from the producer's claimed completion.
The Python gate proves P1 authority rejects late applicability/action and preserves
useful current work. Caller timeout/cancellation retains the actual HTTP task, so
the original response may still be recorded; socket closure is not manufactured
from waiter abandonment. Closed counters distinguish cumulative computations from
live requests/sockets/attempts and are inspected again after actual owned shutdown.
No remote retry/queue/mutation permission is introduced. See the [I13 handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
for selected qualification and limitations.


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

The public `@livekit-ecosystem/delegation-specialist/fixed-policy` export provides
`FixedPolicyRequest`/`FixedPolicyResult`, their strict codecs, `FixedPolicyHandler`,
`FixedPolicySpecialistClient` and `verifyFixedPolicyFacts`. Pass an explicit handler
to `SpecialistServer` to enable version 2; an unconfigured server preserves the
version-1 default. `examples/fixed-policy.mjs` accepts configured request/client/
evidence ports and runs the separate factual check.

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
Projection, refresh, completion, delivery and action remain version-1-only. I18B
adds the explicit native application described below; fourteen full charter rows
and broader integrated release remain planned.

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
- [Project coding instructions](../AGENTS.md)
- [Contract and trust checkpoint](../../../docs/work-items/0025-p3-specialist-contracts-and-trust.md)
- [HTTP/standalone handoff](../../../docs/work-items/0027-p2-standalone-and-p3-http.md)
- [Issued execution checkpoint](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
- [Shared version-one fixtures](../../../contracts/delegation/v1.json)

## Requirements

Use the frozen root pnpm environment with Node 24.22.2 or 26.13.0 and pinned
TypeScript/Vitest. Contract parity tests also require the installed Python 3.14
workspace. HTTP tests use actual, owned loopback sockets; no Docker, provider,
model download or paid credential is required. Supply runtime token digests and
source bytes through trusted application configuration. The example uses synthetic
facts and a newly generated local token.

## Commands

From the repository root after frozen dependency installation:

```sh
corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck
corepack pnpm --filter @livekit-ecosystem/delegation-specialist test
corepack pnpm --filter @livekit-ecosystem/delegation-specialist build
corepack pnpm --filter @livekit-ecosystem/delegation-specialist demo
```

The demo starts one ephemeral server, calls it through the actual typed client,
prints a safe candidate summary and closes owned resources. It performs no business
mutation, durable submission or real-model reasoning.

Public imports are available from the package root and the explicit /http export.
Construct SpecialistServer with LocalTrust and EvidenceRegistry. Its listen method
binds only 127.0.0.1 on an ephemeral port and returns the endpoint. Construct
SpecialistClient with that endpoint and a trusted Bearer header. invoke returns a
DelegationResult; status and cancel return an AttemptObservation. Close both through
try/finally. The client accepts a literal loopback endpoint, never an arbitrary URL,
and performs no redirects or retries.

## Validation

### HTTP and authority

| Route | Required grants | Observation |
| --- | --- | --- |
| POST /v1/invoke | invoke and result for the capability, plus each evidence source | One synchronous scripted result; combined result access is checked before work starts |
| POST /v1/status | result for the exact active attempt | Ephemeral running observation with separate deadline, disconnect, cancel and closing flags |
| POST /v1/cancel | cancel for the exact active attempt | Request observed; an HTTP 202 response does not prove computation stopped |

Every route uses the existing exact DelegationRequest envelope. The body cannot
grant its scope or permissions. Status/cancel never return source bytes, fabricate
durable acceptance, or retain terminal history. After actual work settles and the
original permit is released, later status returns unknown_attempt. A concurrent
same-attempt invocation conflicts. A released attempt has no durable deduplication
record here; the P1 owner must decide any subsequent attempt or reconciliation.

The server computes against authorized source bytes and checks verifyPolicyFacts.
The client independently checks strict response shape, identity, current attempt,
deadline and evidence-reference binding. It cannot independently establish factual
truth without separately supplied source bytes. A source-grounded candidate still
needs current-case applicability and exact consent at the case authority.

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

Trusted configuration may lower server limits. Each connection serves one request;
keepalive cannot create another dispatch and pipelining is rejected. Owned timers
explicitly end sockets/requests; monotonic checks also reject late body, evaluation
and client success when a timeout callback is delayed. Remaining business deadline
is checked against trusted time, not a result's reported completion timestamp.

Cancellation, expiry and disconnect request an AbortSignal. An uncooperative
trusted harness barrier retains the original permit until it actually settles.
Bounded shutdown then reports cleanup_incomplete and can be attempted again after
settlement; it cannot advertise successful cleanup or start replacement work.
The optional beforeEvaluate hook is a trusted harness-only barrier, never a public
executor or something request JSON can select.

The default observer emits finite structured fields and no input, source bytes or
credentials. Synchronous exceptions and asynchronous rejections are contained;
actual failures/drops appear in numeric metrics. Observer adapters own any external
resources they create. No custom exporter or production-capacity claim is added.

Tests use actual loopback requests for useful result/status/cancel progression,
operation grants, deadlines, aborts, raw header/framing/body bounds, socket and
request saturation, pipelining, malformed/late responses, cleanup and safe
observation. Contract tests preserve exact cross-language canonical bytes and
separate schema validity, source identity and factual checks. Missing or skipped
required checks cannot qualify the slice.

## Recovery fault fixture

The test-only recovery-server.mjs composes the unchanged public SpecialistServer
and evidence registry. It adds no durable acceptance, retry, queue or new permission.
Generation A is killed while an actual read-only call is active; generation B observes
a real coordinator socket loss through cooperative AbortSignal, then useful later
calls. Only a public attempt_started event counts invocation, since successful
source resolution can still precede a capacity rejection. Public completion/abort
observations are separate from the P1 result and receipt history.

The bounded journal retains exact scope/wire-attempt/request identities and real
public counters. It refreshes changed metrics after settlement, before replacement
work; a killed process keeps its last running snapshot and cannot advertise graceful
zero occupancy. The normally closed process reports actual requests/sockets/active
zero only after close. No request body selects a hook, module, process, account or PID.

The Python make p3-recovery-check orchestration retains the source and receipt truth
through P1 public ports, with seventeen selected assertions, eight owned kills and
one real SQL issuance graph. The [phase handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records source/installed qualification separately; this fixture alone is not that
gate. No remote durable-status or exactly-once physical computation claim follows.

## Next milestone

The bounded handler/client review and selected shared local gates passed; their
exact evidence belongs to the linked handoffs. The Python runner now calls this
HTTP boundary under P1-issued grants and keeps durable result history with P1.
The separate make p3-completion-check now qualifies the first Python I07B delivery
and exact case-authorized fake-action path using this actual service. Its completion
fixture independently counts four evaluations, holds stale A at an explicit barrier
and observes resource cleanup; it adds no public handler state or permissions.
P3-I08 now runs all codec/evidence bounds in both languages and five named invalid
HTTP output variants under actual issued Python runner attempts, followed by useful
progress. The acceptance-server fixture intentionally hosts an invalid test peer
alongside the actual public specialist server; request JSON selects no test hook.
The I16 bounded standalone image path has selected source/installed qualification.
I17 fixed-policy HTTP remains independently usable. I18A adds explicit durable
policy-v2 Python facades and verified historical observation in both languages;
its selected qualification is recorded in the I18A handoff. The explicit I18B
native Python application uses this unchanged public HTTP capability; its text
profile and broader real-model/modality qualification retain separate phase gates.
