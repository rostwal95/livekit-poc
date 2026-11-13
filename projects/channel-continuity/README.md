# Channel Continuity Kit

Status: Active
Last reviewed: 13 November 2026

The opt-in `./communication` and Python native communication profile preserve
source-qualified response anchors, actual generated text, SDK speech settlement
and client-reported playback. The [I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records qualification and remaining boundaries. Generated text, SDK output, a
browser completion claim and business acceptance are independent facts. Read the
[communication contract](COMMUNICATION.md) before enabling version 7.

The opt-in `./native` server composition and Python `[native]` adapter connect
native `lk.chat` and explicitly committed scripted voice to the same PostgreSQL
inbox and persisted dispatcher. The adapter disables the SDK's automatic text
consumer and suppresses automatic end-of-turn replies; only a claimed dispatch
may request native generation. [The native phase handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records qualification, exact local evidence and remaining boundaries. Generation
completion is an SDK observation, separate from browser playback, consent and a
supplier effect. Scripted ASR maps the local voiced fixture to a fixed transcript;
it is not general recognition or paid inference.

The I14 `./idempotent-fake-sms` capability and explicit outbox recovery controllers
separate ordinary uncertain sends from a cooperating provider's same-key recovery.
A non-idempotent lost response remains unknown and never opens a resend. Explicit
commands retain immutable receipts; idempotent retries keep the original provider
operation, recipient, address and body across distinct local attempt IDs. See
[the send-policy handoff](../../docs/work-items/0035-send-policy-and-action-races.md)
for qualification and boundaries. No physical exactly-once or human-delivery claim
follows from a provider's reported acceptance.

The additive I13 `./callbacks` server export authenticates raw fake-provider reports,
retains immutable attempt-correlated evidence and exposes a deterministic contradiction
view. See [the callback phase handoff](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
for qualification and remaining boundaries. Provider reports do not grant resend authority.

The additive I12 server exports `./outbox` and `./fake-sms-send` provide durable
reply acceptance, versioned authorized routes, recipient-level suppression and
ordinary local fake sends. Qualification and remaining boundaries are recorded in
[the phase handoff](../../docs/work-items/0033-outbound-replies-and-completion-processing.md).
A queued receipt, provider acceptance and human acknowledgement are separate facts.

The opt-in I19 [bounded workload profile](WORKLOAD.md) declares active overload,
retained-capacity replay, actual task settlement and one thousand dormant
conversations. `ChannelInbox.telemetryMetrics()` exposes the ordinary observer's
separate bounded pending/dropped/failure lane. The [workload handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records selected qualification; process samples are observations rather than
production capacity claims. Run `make p2-workload-plan` for its fixed declaration
before the actual `make p2-workload-check`. I20 joined UI remains a separate gate.

## Overview

Build a TypeScript SDK and gateway that preserve a travel-support case across LiveKit voice, browser text and simulated SMS.
The V1 charter defines behavior and stable P2 acceptance IDs.

## Implementation status

P2-I01/I02 implement strict version-1 event data contracts, a real TypeScript text
producer, a pure Python codec and shared positive/negative fixtures. Outputs are
immutable and canonical semantics distinguish retry observations from changed
payloads/destinations. Parsers compare separately trusted scope; they do not
authenticate an adapter, verify association or acknowledge durable acceptance.

Explicit server subpaths now implement scope-bound fake-SMS authentication,
seeded-account association and PostgreSQL inbox/receipts/pending processing intent.
Acceptance follows commit and replay returns the original receipt. I07 adds a bounded persisted investigation-dispatch step and explicit lookup-only
reconciliation. I08 adds a bounded loopback gateway with actual acknowledged-input
process-kill/restart evidence, recorded in the
[current gateway phase](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md).
I09 adds the explicit ./agent-process adapter and trusted worker helper. A live
gateway survives an independently killed scripted worker, observes persisted
claim expiry and replays the same immutable input/case/operation context through
a new worker. Attempts remain visible while the cooperating operation accepts
one logical investigation. I10 adds explicit investigation revision routing through
one selected case authority, with equivalent standalone PostgreSQL and public P1
fixtures. I11 adds immutable exact-quote prompt bindings, linked confirmation routing and a
current-association preflight. I12 adds durable reply acceptance, authorized routes and ordinary fake sends.
I13 adds authenticated provider callback intake, retained evidence and a conservative
v4 reservation veto. I14 adds version 5 immutable provider operations, explicit
lookup/retry controller commands and conservative outbound-wide evidence fences.
The selected native text/committed-audio composition uses explicit owner version 6.
Complete native/media charter scenarios remain separate. See the [verified-intake contract](../../docs/work-items/0024-p2-verified-durable-intake.md)
and [PostgreSQL work item](../../docs/work-items/0026-p2-postgres-inbox.md).
The I06 standalone example now composes explicit inbox, synthetic read-only case,
scripted-agent and pending-operation-inspection ports. Acceptance and preview are
separate: adapter failure cannot erase an observed committed receipt. Actual
fresh processes confirmed the same receipt/operation key after replay. The
operation remains pending/not_executed; no fake business-action durability,
dispatch or delivery is claimed by that preview helper. It rejects nonpending
processing state after a dispatcher has claimed or dispatched the input. The
[phase handoff](../../docs/work-items/0027-p2-standalone-and-p3-http.md) owns final
shared evidence and limitations.

Existing transport echo and M1 intake remain separate foundation capabilities.
The [contract work item](../../docs/work-items/0022-p2-channel-contracts.md) owns
this slice's observed checks and limitations.

The opt-in `./result-receiver` and browser-safe `./result-receiver-types` exports
implement original opaque result acceptance and a separate current-native-grant
read over explicit owner schema v8. The selected sixteen storage and four returning-result assertions passed against
real PostgreSQL, including populated backup/restore. Fresh installed-consumer
qualification is tracked separately in the
[0043 work item](../../docs/work-items/0043-stable-result-delivery-and-return-context.md).
This selected seam does not complete a P2 charter row or the joined voice/text/SMS
browser journey. All seventeen complete P2 charter rows remain planned.

## Documentation

- [Project instructions](AGENTS.md)
- [Source-qualified communication](COMMUNICATION.md)
- [Project design](Design.md)
- [V1 scope and acceptance matrix](../../docs/projects/channel-continuity-scope.md)
- [Shared architecture](../../Design.md)
- [Validation plan](../../docs/validation-plan.md)
- [Technology baseline](../../docs/technology-baseline.md)
- [Harness guide](../../harness/README.md)
- [Local stack setup](../../local-setup/README.md)
- [Local console](../../apps/local-console/README.md)

Read the [granular implementation plan](../../docs/implementation/p2-channel-continuity.md)
for phase gates, task prerequisites and failure evidence. These task IDs are not
product acceptance IDs; the charter remains authoritative.

## Requirements

Use the pinned root Python runtime and frozen uv.lock with all declared extras and development dependencies before the full fast suite. Service, Agents SDK and inference-boundary tests require those dependencies; the pure intake subset remains standard-library-only. No
external inference credentials are needed. Docker and Compose 2+ run the shared
lab with pinned images; see the [local setup guide](../../local-setup/README.md)
for host requirements and lifecycle commands. The
[technology baseline](../../docs/technology-baseline.md) records selected versions
and validation boundaries.

## Commands

Run from the repository root:

```sh
uv sync --frozen --all-extras --dev
corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck
corepack pnpm --filter @livekit-ecosystem/channel-continuity test
corepack pnpm --filter @livekit-ecosystem/channel-continuity build
.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v
.venv/bin/python -m harness list --project p2
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2
.venv/bin/python -m harness run --project p2
```

The final command currently reports incomplete with exit 2 because product
acceptance scenarios remain unimplemented. A passing structural check does not
complete those scenarios. The fast lane runs all current Python suites even when
its structural checks focus on this project.

### Explicit PostgreSQL intake lane

After documented local init/start/prepare-postgres and pinned host Node setup:

```sh
make p2-postgres-check
```

This runs actual association/intake transactions and owned-process commit-before-
acknowledgement termination/replay without P1/P3 services. It creates and cleans
only marked disposable schemas. The fixture shares the existing restricted
runtime credential; it does not establish independent P2 database principals.
It starts no carrier/agent and sends no SMS. Use a fresh --report path with
local-setup/scripts/p2_postgres_check.py when retaining a run. Offline tests never
connect to PostgreSQL or silently skip this lane.

### Standalone fake-carrier demonstration

With the same restricted local PostgreSQL setup and pinned Node prerequisites:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --example
```

This builds current public exports and the example, then runs only the two
standalone cases. The output contains actual accepted/replayed receipt IDs,
stable operation keys and sequence, with pending/not_executed clearly shown.
Two separate processes run examples/fake-carrier.ts through its declared public
package imports. No P1/P3 service, carrier account, model or provider key is used.
Only marked disposable schemas are created and cleaned. No default workspace
state or volumes are reset. Optional --report uses a fresh exclusive path under
.local/validation/p2-postgres; existing reports are never overwritten.

The normal make p2-postgres-check lane also includes these examples in its full
23-case run. The repository package's demo script can run the same compiled entry
against an already prepared demo schema with explicit P2_DEMO_SCHEMA,
P2_POSTGRES_PORT and P2_RUNTIME_PASSWORD. Its runtime process refuses migration
credentials. Prefer the wrapper above for complete setup, validation and cleanup.

The synthetic case adapter is a read-only fixture, the agent produces a scripted
interpretation, and the operation adapter only inspects a pending reference. The
inbox receipt and processing intent are durable; the fake operation observation
is not an executed business action. A standalone helper closes only its preview
resources. Its caller must also close the supplied ChannelInbox, as the example
does even after a preview or cleanup failure.

### Recoverable committed-inbox dispatch

With the same local PostgreSQL and pinned host Node prerequisites:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --dispatch
```

This explicit five-case lane exercises the declared ./dispatch package export,
versioned owner upgrade, concurrent claims/admission, expiry and takeover, bounded
unknown acknowledgements and a real SIGKILL after a separate cooperating operation
fixture commits. A fresh dispatcher recovers the original operation receipt by
lookup. The full lane includes these five cases; the standalone two-case demo
continues to show pending/not_executed. Use a fresh --report path for retention.

ChannelDispatcher requires explicit case, scripted-agent and cooperating
operation adapters. step(accountToken, receiptId) requests one unit of durable
work. reconcile(accountToken, receiptId) only looks up the immutable original
scope/key/payload digest, even after ordinary attempts are exhausted or the sender
is reassigned. It never generates a new plan or invokes accept. inspect returns
a bounded attempt history and the authoritative processing state. dispatched
means the investigation port acknowledged durable acceptance; it does not mean a
business action, carrier send or case mutation completed.

New schemas remain version1 until an explicit upgradeChannelSchemaV2 call with
owner settings. Runtime cannot install, alter or repair its schema. Upgrade
preserves canonical input, receipt, sequence, association and operation key.
Quiesce serving processes for an owner upgrade and take a restorable database
backup for retained deployments; the disposable qualification proves preservation
and rejects drift, not a general production backup/restore deployment procedure.
The owner chooses immutable dispatch limits at upgrade: defaults are two active
leases, three attempts, a 5,000ms lease and 250ms retry delay. Qualifying fixtures
use a 500ms lease and 20ms delay to exercise actual expiry. The current global
admission guard favors correctness over throughput and is not a scale benchmark.

Prepared investigation payloads are immutable and bounded to 32 KiB. The store
reserves possible_external before invoking accept outside database locks. An
unknown acknowledgement stays uncertain; a lease protects local observations,
not an external execution fence. The operation adapter must durably deduplicate
scope/key/digest and provide authoritative lookup. Its fixture is stored in a
separate marked schema and is not a second SDK business-execution ledger. No
background scheduler, hidden memory queue or automatic retry loop is installed.
Two locally admitted calls have a whole-step deadline; timed-out ignored adapter
work retains its slot until settlement, and incomplete cleanup is reported.

### Bounded fake-SMS gateway and restart demonstration

With the same explicit local PostgreSQL setup:

```sh
make p2-gateway-check
```

This runs three real process/socket cases using the declared ./gateway export:
normal authenticated acceptance and dispatch, SIGKILL after a flushed HTTP receipt
but before dispatch, and useful progress after a revoked sender is blocked.
Fresh gateway processes recover due input from PostgreSQL; no acknowledgement-owned
memory queue carries it. Replay preserves the original receipt, operation key,
prepared input and cooperating acceptance. The complete 23-case PostgreSQL lane
includes these cases. The case/agent adapters are synthetic and read-only; the
operation fixture persists independently and grants no booking authority. Native
voice/browser, a real carrier and model quality remain separate gates.

Applications construct ChannelGateway with explicit database, integration,
accounts and ports settings. The finite account seeds supply trusted recovery
credentials; request JSON cannot supply a processing scope. listen() binds only
127.0.0.1 and defaults to an ephemeral port. The routes are:

| Route | Meaning and authentication |
| --- | --- |
| POST /webhooks/fake-sms | Exact raw JSON with application/json, Content-Length, X-P2-Timestamp and X-P2-Signature; existing signed provider and current association checks precede durable acceptance |
| GET /receipts/{id} | Bearer account credential; returns scoped processing observation, never action/booking completion |
| GET /health | Local process/driver health; does not prove model, carrier, business execution or database readiness for a future operation |

The host must explicitly install/upgrade v2 before startup; runtime receives no
owner credential and executes no DDL. One owned driver polls due pending/expired
claims with persisted attempt limits. It rotates configured accounts and bounds
each candidate page to 1–16 (default four), with a two-second tick eligibility
budget and 20–1,000ms cadence (default 100ms). Each existing dispatcher step has
its own finite deadline. Uncertain exhausted work requires explicit SDK lookup-only
reconciliation; the gateway cannot invent another acceptance.

The listener bounds sockets to 16, active requests to four, raw headers to 16/8KiB,
header time to one second and body time to two seconds. Raw fake-SMS input stays
within 32KiB; responses within 16KiB and one second. Keep-alive/pipelining, duplicate
headers, transfer encoding and arbitrary routes do not expand resources. The
startup observer budget defaults to five seconds (20–10,000ms); caller timeout
retains underlying I/O until actual cleanup and cannot leave a late serving bind.
Close defaults to two seconds (20–5,000ms), stops admission/polling and observes
actual sockets/handlers/driver before closing both SQL owners. Incomplete cleanup
is a failure. Observer notifications are capped at eight; the application owns
any external resources created by its observer.

Normal ingress does not pause committed work. Only the explicit trusted
harnessAfterAcknowledgement test hook gates dispatch while the fixture observes
a fully flushed receipt; request data cannot choose that hook. Acknowledged means
persisted input, dispatched means cooperating investigation acceptance, and
neither means a completed booking action. Future default Docker/UI composition is
separate from this installed library and explicit process demonstration.

### Isolated scripted agent process

The server-only ./agent-process export provides AgentProcess and runAgentWorker.
Constructing either library starts no listener or child. Application configuration
selects a trusted absolute Node module and finite allowed account scopes; received
message/model data cannot select code, environment, scope or process IDs.

```ts
import { AgentProcess } from '@livekit-ecosystem/channel-continuity/agent-process';
const agent = new AgentProcess({
  modulePath: '/absolute/path/to/trusted-scripted-worker.mjs',
  allowedScopes: [{ tenantId: 'tenant-a', accountId: 'account-a' }],
});
// Supply agent.port as the gateway/dispatcher's plain agent port.
// The application closes both gateway and agent in its lifecycle finally block.
await agent.close();
```

The trusted worker module calls runAgentWorker with its own allowedScopes and a
scripted read-only prepare function. The exact canonical stdin context digest
binds the returned scope, receipt, operation key, case revision and message facts.
Each explicit prepare call owns one fresh POSIX process group. Default limits are
one active worker (configurable up to two), one-second work budget, 32 KiB input,
2 KiB response, 4 KiB stderr and one-second cleanup observer budget. Abort/timeout
rejects the waiter, terminates its owned group and retains the actual slot until
child exit, pipe close and group disappearance. There is no implicit retry queue.
The gateway/dispatcher owns persisted retry eligibility separately.


The succeeded counter and settled(code=ok) event describe a validated worker that
has already exited and whose group/streams are gone. A slow synchronous observer
can still delay caller delivery: the final signal/monotonic guard rejects that
late delivery and increments waiterRejected. Known worker-completion observations are
not relabelled as a successful caller response. Cleanup failures retain the actual
slot until the group is observed gone, including unexpected cleanup exceptions.

Only explicitly configured P2_AGENT_ environment fields enter the child, at most
16 fields/4 KiB. No ambient PG, provider, Node-options or target selectors are
inherited. Module code is trusted and must keep its descendants inside the owned
process group. Local process isolation does not establish a memory/CPU sandbox,
remote-provider cancellation, model quality or production capacity. Applications
own observer-created resources and close AgentProcess separately from the gateway.

With the documented local restricted-role PostgreSQL setup:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --agent
```

This selected case uses actual gateway HTTP, an independent owned scripted agent,
a PostgreSQL-clock lease observation and SIGKILL before any prepared/external
operation. It then verifies two identical context hashes, visible attempts and one
logical operation acceptance. The full 23-case lane includes all earlier 22 cases.
Only synthetic data and marked disposable state are used; native model/media and
complete P2 acceptance remain separate.

## Explicit investigation revision routing

The server-only ./routing export provides RevisionRouter, CaseAuthorityPort,
CaseAuthorityHttpClient, fixed RoutingError codes and a strict command producer.
Routing is an explicit application call after intake; the gateway/dispatcher does
not automatically consume these commands. The accepted body is structured JSON,
not natural-language interpretation:

```ts
import { encodeRevisionCommand } from '@livekit-ecosystem/channel-continuity/routing';

const body = encodeRevisionCommand({
  schemaVersion: 1,
  kind: 'case.revise_investigation',
  expectedRevision: '0',
  request: {
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: 'DEMO-BK-001',
    newCheckIn: '2030-12-11',
    investigationConsent: true,
  },
});
```

Persist this body through the verified input adapter. RevisionRouter.route takes
only the authenticated account credential and original receipt ID. It reads that
accepted body and derives scope/case/operation/message identity from the retained
record; there is no body/proposal/scope override argument. Provider timestamps
remain diagnostic observations. Expected revisions are canonical decimal strings
including zero through the PostgreSQL signed 64-bit maximum. The optional numeric
event revision must agree with the command. Unsupported/noncanonical text causes
clarification without an authority call.

The selected authority returns a known revised/unchanged snapshot or a fixed
conflict/unknown outcome. A current inspection is an independent observation.
After a lost committed reply, matching current payload/revision cannot establish
which command won. There is no automatic retry, rebase, durable revision-command
receipt or inference of original acceptance. Investigation consent permits a case
request revision; exact quote confirmation and supplier mutation remain separate.

Applications construct the router from an AcceptedInputPort, CaseAuthorityPort
and at most 64 trusted scope/case bindings. They close the router and supplied
inbox/authority clients independently. Its default two slots and two-second
budget are bounded; timeout/abort retains an ignored adapter's actual slot until
settlement. CleanupIncomplete never certifies a clean shutdown. Metrics and
fixed event/code logs exclude body, credentials and case identifiers.

Standalone composition uses the separate ./reference-case export:
installReferenceCaseSchema explicitly creates a marked v1 synthetic authority with
1–64 owner-seeded cases; ReferenceCaseAuthority serves existing state with two
connections/active operations and no runtime DDL. Integrated composition selects
CaseAuthorityHttpClient and the explicitly started local application bridge in
local-setup/scripts/p2_case_bridge.py. That bridge maps trusted account/case
bindings to preconstructed public P1 CaseControlClient values. It calls only case
and revise; integrated mode never creates a reference copy of P1 case state.
There is no implicit bridge deployment or dependency on a P3 service.

ChannelInbox.inspect authenticates original retained-account access. It does not
revalidate a sender's current association, and the router adds no atomic
association-revocation fence. Native committed input, confirmation association,
revocation races and complete P2-05/P2-12 remain separate gates.

With the documented restricted-role local PostgreSQL setup:

```sh
.venv/bin/python local-setup/scripts/p2_routing_check.py
```

The equivalent fixtures use actual signed SMS, PostgreSQL locks and an observed
two-caller blocking graph. They require one revision winner/one conflict despite
skewed provider times, valid next-revision progress, unchanged requests, original
receipt replay and postcommit lost-ACK uncertainty. Independent owner inspection
checks the complete P1 mapping/request and zero quotes/confirmations/intents/
supplier effects. Only marked disposable state is removed. This selected I10
scope does not register a complete charter row or qualify native media.

## Linked exact confirmation

The server-only ./confirmation export adds ConfirmationRouter and the separate
ConfirmationHttpClient capability. ./prompt-registry provides explicit
installPromptRegistry and PromptRegistry. The default codec and fake-SMS v1 wire
are unchanged. ReferenceCaseAuthority remains investigation-only; applications
supply a narrow atomic ConfirmationAuthorityPort for standalone use. Integrated
mode uses public P1 exact-quote commitment through the opt-in local bridge.

A trusted controller obtains a real supplier-bound v2 quote through the public P1
producer, then publishes an immutable prompt with a distinct publisher credential.
It binds account, logical case, conversation, response ID, decimal revision,
quote ID, SHA256 and the complete original canonical quote JSON. Registry
publication validates the bounded byte envelope and digest; the P1 parser and
atomic authority validate the actual issued quote. Opaque quote bytes retain
large integer literals exactly. Quote IDs follow P1's canonical UUID contract,
including deterministic UUIDv5 proposals; operation/intent/effect IDs remain UUIDv4.

The publication credential is a trusted application role, separate from seeded
account credentials. No model tool or input body selects it. The local runtime
still uses the documented shared PostgreSQL role. Response identity is unique
within tenant/account: reusing it for another case, conversation or quote conflicts.
Existing publication replay returns its original observation even at capacity;
new publication is explicitly rejected. Prompts have no automatic pruning or
permanent agent allocation. A recorded prompt does not assert sending, playback,
hearing or comprehension.

An accepted SMS can explicitly answer `YES <responseId>`. Bare YES requires both
an existing trusted event replyToResponseId and expectedCaseRevision; without them
it asks clarification. The optional structured command preserves the full decimal
revision and exact digest:

```ts
import { encodeConfirmation } from '@livekit-ecosystem/channel-continuity/confirmation';

const body = encodeConfirmation({
  schemaVersion: 1,
  kind: 'case.confirm_quote',
  responseId: prompt.responseId,
  expectedRevision: prompt.revision,
  quoteDigest: prompt.quoteDigest,
  explicit: true,
});
```

ConfirmationRouter requires both retained authenticated inspect and the separate
inspectForConfirmation input method. It resolves the original immutable prompt,
then performs the current original-association preflight immediately before
commitment, checking that the complete original input identity still matches.
ChannelInbox.inspectForConfirmation rejects a revoked/reassigned original epoch;
ordinary retained history remains readable by its original account. This is a
preflight, not an atomic P2-to-P1 revocation fence. A revocation after preflight
remains outside this slice's guarantee.

Only original explicit user consent plus the bound prompt reaches the authority.
P1 validates scope, exact quote/revision, expiry, cancellation and command identity
inside its commitment transaction. Stale or ambiguous input asks clarification;
there is no current-case read/rebase or model-derived consent. The original inbox
operation UUID is the confirmation command ID. Lost commitment acknowledgement
stays unknown. An explicit same-input replay can retrieve P1's original intent/
effect receipt, including after case cancellation/expiry while association remains
eligible. This router rejects replay after association revocation; it exposes no
lookup-only historical-receipt route. The durable P1 receipt remains a fact.

The router owns at most two calls by default, with two-second observation and
one-second close budgets. Ignored adapters retain actual capacity after timeout.
The HTTP client uses a fresh bounded loopback socket, requires Connection: close
and retains request/socket ownership until both actually close. Applications also
close their input, prompt registry and authority clients. The bridge requires
allow_confirmation=True explicitly; I10-only bindings do not gain confirmation.

```sh
.venv/bin/python local-setup/scripts/p2_confirmation_check.py
```

The actual local gate covers signed stale/unlinked/current replies, publisher
separation, immutable nonce/cap behavior, an observed two-caller revise/confirm
race, lost ACK/original replay, one leased fake supplier change, late cancellation,
known revoked/reassigned input denial and independent PostgreSQL/supplier truth.
Default UI/Compose, native media, real inference, automatic gateway routing and
full P2-06/P2-12 registration remain separate. P2 processing_intents describe the
existing investigation dispatcher; exact-confirmation truth is the P1 receipt.

## Validation

The [V1 acceptance matrix](../../docs/projects/channel-continuity-scope.md) defines required scenarios.
The [shared validation plan](../../docs/validation-plan.md) separates deterministic
correctness, actual local media and real-model evidence. Local-ready V1 requires
the designated local checks; portfolio-ready V1 adds the required real-model runs,
review, benchmark evidence and demonstration. Harness reports live under ignored .local/harness. The shared local stack has
separate readiness/transport smoke checks and persistent volumes. Its actual
text/audio checks do not provide STT, LLM, TTS or product V1 evidence. Normal
stop/start preserves current local state; use the documented explicit reset only
when synthetic data removal is intended.

## Next milestone

The selected local I12 durable-reply, I13 authenticated-callback and I14 explicit
uncertain-send slices are implemented and qualified by their linked phase handoffs,
including isolated installed-package consumption. The selected I15/I16 native
text/committed-audio composition has its own current handoff. The opt-in I17
communication implementation and qualification boundaries are recorded in its
linked handoff. The opt-in I18 current-case read/profile is described in
[REHYDRATION.md](REHYDRATION.md), with selected evidence and limits in its
[handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md). I19 workload qualification is tracked in its [separate handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md). I20 joined observability and the later complete package/release gates remain separate.
Preserve verification, association, durable input, exact consent and immutable
operation identity. Full P2 charter acceptance, broader native/media, integrated
UI, supported-platform release and load retain separate gates. Provider reports
do not prove physical delivery.

## Durable outbound replies

With the same restricted local PostgreSQL and pinned Node setup:

```sh
.venv/bin/python local-setup/scripts/p2_outbox_check.py --report .local/validation/p2-outbox/fresh-run.json
```

The explicit lane uses only new UUID-owned schemas and a synthetic loopback
carrier. It performs an actual owner pg_dump/psql backup/restore, original/new
inbox-dispatch compatibility, owned kill after committed enqueue, a real
revocation/reservation blocking graph, route/suppression/reassignment negatives,
ordinary fake acceptance/definitive failure and fresh-process unknown inspection.
It does not reset application volumes or call providers. Use a fresh report path;
failed, missing, skipped, timed-out or incomplete-cleanup runs do not pass.

Owner setup is explicit and requires serving processes to quiesce before upgrade:

```ts
import {
  installChannelSchema, upgradeChannelSchemaV2, upgradeChannelSchemaV3,
} from '@livekit-ecosystem/channel-continuity/migrations';

await installChannelSchema(ownerDatabase);
await upgradeChannelSchemaV2(ownerDatabase);
await upgradeChannelSchemaV3(ownerDatabase, {
  maxReplies: 1000, maxRoutes: 256, maxAttempts: 3,
});
```

Existing v1/v2 profiles continue to work; the outbox requires v3. Repeating owner
installation or an older upgrade validates v3 and preserves it. The migration
owner is trusted; runtime lacks DDL and canonical UPDATE/DELETE/TRUNCATE privileges.

```ts
import { ChannelOutbox } from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';

const carrier = new FakeSmsSendClient(
  { host: '127.0.0.1', port: fakeCarrierPort }, fakeCarrierAuthorization, providerScope,
);
const outbox = new ChannelOutbox(
  runtimeDatabase, fakeSmsIntegration, seededAccounts,
  [{ token: publisherToken, scope: accountScope, caseId, conversationId }], carrier,
);
try {
  const receipt = await outbox.enqueue(publisherToken, {
    schemaVersion: 1, outboundId, responseId, body: 'Your investigation result is ready.',
  });
  await outbox.selectRoute(accountToken, {
    senderId, associationVersion, expectedRouteVersion: '0',
  });
  const send = await outbox.send(accountToken, receipt.outboundId);
  const retained = await outbox.inspect(accountToken, receipt.outboundId);
  // Render send.status and retained evidence; never invent delivery or hearing.
} finally {
  const results = await Promise.allSettled([outbox.close(), carrier.close()]);
  if (results.some(result => result.status === 'rejected')) throw new Error('CleanupIncomplete');
}
```

The application supplies and separately closes any ChannelInbox used to establish
associations. Import opens no listener or connection. Runtime APIs authenticate
retained recipient reads; a newly reassigned sender cannot read the old recipient's
outbox. `pending(accountToken, limit)` returns at most 32 eligible logical IDs and
owns no scheduling queue. Each explicit `send` admits one attempt at most.

A publisher is a distinct trusted application capability. Its binding supplies
recipient identity; the draft cannot select tenant, account, case, conversation,
provider or address. The original scoped outbound UUID, response reference and
exact 4096-byte UTF-8 body are immutable. Equal replay returns its original
receiver/receipt/digests/time even at capacity. Changed payload conflicts. Receiver
identity persists in owner-installed settings. The opt-in [v8 result receiver](#original-result-receipts-and-current-native-reads)
uses the original P1 delivery UUID while retaining its result digest separately;
this envelope digest does not replace P1 result identity.

Route version is a decimal int64 CAS, with zero meaning absent. Selecting a route
requires its current exact verified association. `setSuppressed` is scoped to the
immutable tenant/account/conversation; suppression survives address replacement.
Missing, revoked or suppressed routes hold before creating a send attempt.
Reservation shares the inbox admission guard with association changes and records
the exact address/epoch/version before external I/O. Changes committed afterward
cannot cancel an already admitted call or retarget its old attempt.

An immutable possible-send record precedes the carrier call. A separate immutable
result records `accepted_by_provider` or `definitive_not_accepted`. A missing or
unvalidated result is `unknown` and blocks another send, including after restart
or route change. Only definitive nonacceptance permits another explicit attempt,
with a fresh local attempt/provider operation UUID and the same logical recipient.
The provider key for an unknown attempt remains frozen. There are no automatic
retries, callbacks or provider lookup/resend policy in this slice. Provider acceptance
is not physical delivery, playback, hearing, human acknowledgement or booking consent.

Defaults are 1000 retained replies, 256 route records and three attempts/reply;
owner maxima are 10000/10000/five. Actual sends default to two per instance (maximum 4),
with a 2-second waiter (maximum 5 seconds) and 2-second close. SQL uses the existing two connections and finite
statement/lock/query budgets. These are configured bounds, not measured capacity
or a global physical-send concurrency guarantee. Timed-out ignored work retains
actual capacity; late known results can persist while the caller stays unknown.
The application owns carrier shutdown separately and must inspect incomplete cleanup.

## Authenticated callback evidence

The server-only `./callbacks` export provides `CallbackInbox`,
`createFakeSmsCallbackIntegration`, `signFakeSmsCallback` and the pure
`reduceCallbackEvidence` rule. Imports start no listener. Supply explicit database
settings, a callback-specific integration and `SeededAccounts`. The application owns
its HTTP listener; the SDK owns authentication, its SQL pool and admitted tasks.
An existing inbound-SMS integration is not a callback credential.

Run the quiesced owner upgrade after v3:

```ts
import { upgradeChannelSchemaV4 } from '@livekit-ecosystem/channel-continuity/migrations';
import {
  CallbackInbox,
  createFakeSmsCallbackIntegration,
} from '@livekit-ecosystem/channel-continuity/callbacks';

await upgradeChannelSchemaV4(ownerDatabase);
const integration = createFakeSmsCallbackIntegration(providerScope, callbackHmacKey);
const callbacks = new CallbackInbox(runtimeDatabase, integration, accounts);
const receipt = await callbacks.accept(rawBody, { timestamp, signature });
const evidence = await callbacks.inspectAttempt(accountToken, { outboundId, attemptId });
await callbacks.close();
```

`ownerDatabase` belongs only to the explicit setup job; serving code uses the
restricted runtime role. `callbackHmacKey` is supplied separately from the inbound
SMS key, never transmitted to account clients. This is synthetic fake-carrier
qualification, with no paid provider or default callback service.

| Boundary | Contract |
| --- | --- |
| Raw callback | Exactly eight schema1 fields: schemaVersion, eventId, attemptId, providerOperationKey, requestDigest, providerMessageId, state, occurredAt |
| Authentication | Callback-specific HMAC domain/key over trusted provider scope, transport timestamp and exact raw UTF-8 bytes; 60-second window on every retry, including replay at cap |
| Identity | Scoped provider event ID; semantic canonical payload includes occurredAt/message ID/state, while signature and retry envelope timestamp are excluded |
| Correlation | Original persisted attempt ID, provider operation key, request digest and provider scope; business recipient/case comes from that immutable request |
| Receipt | Original receipt UUID, event/attempt IDs, canonical payload digest and database accepted time; replay returns the original receipt |
| Account read | Retained account/case/conversation authentication; reassigned phone owner cannot inherit old reports |
| Unknown | No known send result is required; reports arriving before a normal send ACK remain separate evidence |
| Contradiction | Delivered/read plus failed, incompatible provider message IDs or positive evidence against definitive send nonacceptance remain visible as conflicted |
| Send veto | Any retained callback on any prior attempt blocks a NEW v4 reservation that would otherwise be eligible; never retries or retargets |

The reducer is commutative and timestamp-independent. It retains the strongest
reported state, all reported provider IDs and fixed conflict reasons. Accepted then
failed can be a normal provider lifecycle. A reported read or delivery is provider
evidence, not human acknowledgement, consent or a physical-delivery guarantee.
Original immutable send results remain available alongside the report view.

Callback and new-send reservation share the existing admission guard. Callback first
vetoes a later reservation; reservation first retains its admitted frozen attempt.
A later report cannot retract an already possible external call. `pending` is an
advisory scan; `reserve` repeats the check atomically. v3 profiles retain their
previous behavior until explicitly upgraded to v4.

Default retained caps are 10000 observations globally and eight per attempt;
maximums are 100000/32. Reads and authenticated equal replay remain available at
capacity. There is no physical pruning; receipts and provider event identity survive
for the profile lifetime. Four actual calls share two SQL connections. Waiters default
to two seconds (maximum five); timeout/abort retains actual work until settlement.
A close timeout reports `CleanupIncomplete`, and ownership remains until actual close.

Metrics count accepted/replayed durable observations, public rejection/conflict/auth
failures, waiter rejections, actual active work and bounded telemetry failures/drops.
Events use fixed enums only, with no raw body, phone, account, event or key labels.
A late committed observation and a timed-out waiter are separate measured facts.

From the repository root:

```sh
make p2-callbacks-check
.venv/bin/python -m unittest tests.test_p2_callbacks_gate
pnpm --filter @livekit-ecosystem/channel-continuity typecheck
pnpm --filter @livekit-ecosystem/channel-continuity test
```

The actual fixture owns bounded loopback HTTP peers, distinct runtime/owner processes,
SQL-cancel upgrade rollback, a verified owned SIGKILL after callback commit but before
HTTP acknowledgement, fresh replay, and populated v4 pg_dump/psql recovery. Its provider
ledger is independent synthetic test tooling. Run the prior outbox24, routing22,
confirmation18 and recovery23 lanes for shared storage compatibility. The isolated
installed npm consumer checks strict public types without checkout imports or
`@types/pg`; see the stable phase handoff for exact evidence. Those I13 callback
observations alone did not qualify ambiguous-send recovery. The separate
[I14 handoff](../../docs/work-items/0035-send-policy-and-action-races.md) records the
current uncertain-send evidence. Complete P2 charter/native scenarios remain pending.

## Explicit uncertain-send recovery

Install owner versions1→2→3→4→5 under quiescence with
`upgradeChannelSchemaV5`. Existing rows retain their bytes; v4 attempts are adopted
permanently as ordinary operations. The runtime never upgrades or repairs a schema.
Use a separately configured `recoveryControllers` credential inventory. Account and
publisher credentials cannot authorize recovery commands.

`reconcile(token,{commandId,outboundId,attemptId})` records one exact lookup
permission and its separately sourced observation. `retry(token,{commandId,
outboundId,expectedAttemptId})` may reserve one new invocation only after current
permission, callback and retained-operation checks. Replaying either original
command returns its original receipt without invoking either carrier method.
`recoveryCommand(accountToken,commandId)` and `inspectRecovery(accountToken,
outboundId)` expose retained history, including unresolved permissions and conflicts.
The application closes the outbox and supplied HTTP carrier client independently.

The cooperating fake capability binds a stable key to the original operation
payload before its first possible call. A known terminal nonacceptance is a durable
per-key tombstone; lookup absence and transport failure remain unknown. A matching
accepted observation holds a new retry. Any callback on any earlier attempt also
vetoes a new reservation. Different route epochs may reauthorize the same original
address; they cannot change the operation payload. Historical lookup after revocation
can record truth but cannot restore send permission.

Run `make p2-send-policy-check`, all package unit/type/build checks, the earlier
callback/outbox/routing/confirmation/recovery lanes and an isolated installed-package
consumer. The selected synthetic lane includes real HTTP, SQL contention, owned
process kills and populated v5 backup/restore. Provider-contract contradictions are
retained and stop future calls; they cannot retract an already admitted external call.

## Native application composition

Install the Python distribution with its explicit `native` extra to obtain the
frozen compatible Agents 1.8.11 edge. The default Python codec import remains free
of SDK initialization. TypeScript consumers import server capabilities from
`@livekit-ecosystem/channel-continuity/native`; importing starts no listener.

The trusted application configures a separate publisher, account credential and
room-binding bearer. A publisher binds immutable tenant/account/case/conversation,
room and participant before an input is admitted. Browser tokens contain RTC
permission only. Neither a room label, SDK stream ID nor a request-body account
selector grants durable acceptance. Each input has an explicit stable UUID;
equal replay retains its original receipt, acceptance sequence and logical
operation, while changed bytes conflict. The ingress JSON budget is 16384 bytes
for at most 2048 raw UTF8 text bytes, including worst-case JSON escaping.

Owner `upgradeChannelSchemaV6` adds bounded native grants after version 5 under
maintenance/quiescence. Serving code performs no DDL. The same existing inbox,
conversation sequence and processing intents own acceptance. New prepare and
reservation acquire the original admission/binding locks and recheck fresh
PostgreSQL time; expired/revoked grants block new work. Original account-authorized
history remains available. An expiry after possible external admission cannot
retract that already admitted call. Disconnect alone does not revoke a grant.

`NativeRuntime` owns two bounded text readers, actual intake and preparation work,
manual voice capture, SDK lifecycle and bounded observations. Injected recognition
must capture the original input UUID before asynchronous work and expose a genuine
immutable final snapshot plus actual pending work. SDK interim promotion and
commit completion alone do not establish final provenance. Every completed-user-turn
hook raises `StopResponse`; generation happens only through the dispatcher bridge
after all original handoffs settle. Repeated voice commit uses the retained turn
result. A new generation has a separate UUID and may repeat after recovery while
the cooperating logical operation remains stable.

The example `examples/native_lab.py` is a separately launched, loopback-only,
scripted application with bounded HTTP and RTC ownership. The root native gate
owns its PostgreSQL, LiveKit and browser orchestration; the example reads only its
explicit private fixture/media files. Applications separately close the native
inbox/gateway, HTTP agent adapter, intake client, SDK runtime, RTC room and their
injected providers. Timeout preserves actual in-flight work; incomplete cleanup
cannot be reported as success. The prepare client Authorization argument is `Bearer <token>` with exactly 43 token characters;
native publisher/account/binding credentials are 32–128 characters and must differ.

The isolated native page is an application demonstration. It distinguishes accepted
input, dispatch and SDK generation observations. The separate I17 communication
profile adds generated/SDK/browser evidence and response-scoped interruption; its
measured gates are recorded in the linked handoff. The separate I18 read/profile has its own contract and handoff; real
recognizers/inference, broader load and complete P2 acceptance retain later gates.

The `nativeGenerationAttempts` producer counts dispatched preparation attempts
admitted after input/hook settlement and the first monotonic deadline check. It is
separate from actual model invocations, which the scripted application independently
records. A delayed started-observation publisher can exhaust the remaining budget;
a fresh deadline/closed check then prevents any new SDK call. Completed replies
count only actual successful SpeechHandle settlement. Observer failures include
contained synchronous/asynchronous observer and logging-sink failures; pending and
cap-eight dropped observations are separate fixed counters. Library import attaches
no handlers, while the explicit application sanitizes SDK log fields and exceptions.

## Response and playback evidence

Enable the opaque `createCommunicationIntegration` with separate trusted publisher,
SDK and browser credentials; use `CommunicationInbox`/`CommunicationGateway` from
`./communication`. Explicit owner `upgradeChannelSchemaV7` adds three tables after
v6. Runtime performs no DDL. `beginResponse` binds original accepted input receipt,
operation, generation and SDK speech identity; `observeSdk` and `observeBrowser`
append immutable facts. Account-authenticated `inspectResponse`, `responses` and
`observations` read bounded coherent projections. The default native profile stays
on its existing protocol and eighteen metrics.

The native Python profile adds `NativeCommunicationHttpClient` and source capture
through public SDK nodes. Its two-chunk bounded stream forwards text to speech
while collecting at most 4096 UTF-8 bytes. Only normal actual source exhaustion
publishes full generated text. Actual LLM/TTS tasks remain owned beyond a forced
SpeechHandle watchdog settlement; incomplete/error/overflow cannot create known
preparation. A settled interrupted scripted read-only preparation with complete
model output can remain known without automatic regeneration.

Use the root communication-storage and playback-media gates documented in the
handoff, alongside unit/type checks, the preceding native gate and old P2 storage
regressions. Installed package checks prove public APIs outside the checkout;
unit/mock, actual PostgreSQL, process-kill and browser/audio evidence remain distinct.


## Current-case context across rooms and channels

Use `./rehydration` and `channel_continuity.native_rehydration` for the opt-in
read-only current-case profile. The [contract](REHYDRATION.md) defines current grant
admission, raw already-accepted SMS authentication, coherent P2 history and separately
observed P1 facts, byte/page bounds, explicit idle refresh and original room identity.
The [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) records selected qualification.
Context loading creates no accepted input, prepared operation, reply or generation.
Old generated/playback evidence remains inert history. Read revision zero is
supported, while current native dispatch/communication retain their explicit
positive-revision domain; the profile rejects unsupported zero-revision native
input before acceptance. Broader valid-domain integration remains a release gate.


## Original result receipts and current-native reads

This implemented opt-in API requires the existing outbox and a native inbox on the
same database/schema. During an explicit quiescent owner step, call
`upgradeChannelSchemaV8(ownerDatabase)` from `./migrations` after v7. It returns
the existing receiver UUID and never rotates it. Serving code performs no DDL;
old APIs and owner upgrade entrypoints validate v8 without downgrading it.

A configured application supplies its existing owners and distinct capabilities:

```ts
import {
  ChannelResultReceiver, ChannelResultReader, parseResultIntent,
} from '@livekit-ecosystem/channel-continuity/result-receiver';

const route = { scope, caseId, conversationId, recipientId };
const receiver = new ChannelResultReceiver(outbox, {
  receiverId, bindings: [{ ...route, publisherToken }],
});
const reader = new ChannelResultReader(outbox, nativeInbox, currentCases, {
  receiverId, bindings: [route],
});
const intent = parseResultIntent(originalP1Canonical);
const receipt = await receiver.accept(publisherToken, intent);
const original = await receiver.find(publisherToken, intent);
const view = await reader.native(currentNativeBearer, intent.delivery_id);
```

`accept` and `find` require the configured publisher capability. A native grant
cannot publish; it authorizes only the separate scoped read. The reader's route
bindings contain no publisher secret. This integration accepts the lowercase
P3-compatible identifier subset of one through 64 characters; unsupported or
longer P2 identifiers reject rather than being truncated or remapped.

The intent is exact sorted ASCII P1 canonical JSON, bounded at 16,384 bytes. Its
strict base64 body decodes to at most 8,192 bytes and must match the original
`result_sha256`; timestamp integers stay within P1’s 0–4,102,444,800,000 ms range.
The six receipt fields remain `delivery_id`, `receipt_id`,
`receiver_id`, `recipient_id`, `result_sha256` and `accepted_at_ms`. One protected
outbox transaction retains that original intent and enqueues the fixed notice,
“Your review result is ready. Rejoin this conversation to view it.” Its body is
bounded at 4,096 bytes and has a different digest. The original delivery UUID is
the outbound UUID; exact replay retains the original receipt even at capacity,
while changed intent bytes or an ordinary reply UUID collision conflict.

Both facades share the existing outbox pool of two SQL connections and four
actual-call reservations. The receiver admits at most two active operations; the
reader admits one. The reader retains its reservation while SQL is released for
one public P1 current-case read, then locks and rechecks the original native grant
with fresh database time before disclosure. A native read request is bounded at
256 bytes in the local qualification host; the SDK view is bounded at 32,768 bytes. `view.observed` separates P2 read, case
read and disclosure times with `atomic: false`; case revision equality does not
grant result applicability, execution or consent. Receiver history remains
available after native revocation, while current-channel disclosure is denied.

Default caller deadlines are two seconds for the receiver and three seconds for
the reader; cleanup observation is two seconds. Timeout or `CleanupIncomplete`
retains actual ownership. Close these facade owners before their application-owned
outbox, native inbox and current-case client. Ordinary possible SMS sends remain
unknown and do not acquire automatic resend permission from result acceptance.

From the repository root, `make p2-result-receiver-plan` declares the isolated
schedule without starting resources. `make p2-result-receiver-check` requires its
reviewed restricted PostgreSQL setup and fixed bounds. Its selected sixteen
storage and four return assertions passed, including commit-before-ACK recovery,
lookup-only reconciliation and backup/restore. These return reads use native grants
without an RTC room. The separate `make p2-result-receiver-package-plan` and
`make p2-result-receiver-package-check` qualify isolated installed APIs; their
twenty copied fake-port tests and eight existing offline assertions do not repeat
the twenty actual storage/return assertions. Each lane requires its own passing
report; source execution does not substitute for an installed consumer.

## Read-only channel operations

The separate `./operations` and browser-safe `./operations-types` exports provide
an opt-in fixed-scope operator view. `OperationsReader` joins the existing bounded
P2 snapshot, a separately observed public current-case result and a fresh protected
grant check. `OperationsReadServer` and `OperationsHttpClient` expose literal-loopback
GET reads with request correlation and signed, source/scope/section-bound cursors.
No body or cursor grants mutation, retry, resend, dispatch or playback authority.

The [operations contract](OPERATIONS.md) defines current versus historical facts,
explicit refresh, process-local metric/span sources, exporter failure isolation and
actual owner retention. `examples/operations-lab.ts` composes supplied owners without
creating another database pool or work queue. Applications separately close their
inbox, current-case adapter and injected exporter transport. A read timeout or
Forget clears a caller view without proving that underlying work stopped.

The dedicated console page is built with `make p2-operations-build`; it is separate
from the default P1 console and native controls. `make p2-operations-plan` declares
the fixed local schedule without starting services, while `make p2-operations-check`
requires the reviewed restricted-role local setup and explicit gate bounds.
Normal PostgreSQL/browser results and isolated-package qualification are recorded
in the current phase work item. No complete P2 charter row is closed by
an offline model test, a process sample or this selected operations interface.

### Operation client without provider scaffolding

The public `./starter` export now accepts a narrow OperationClientConfig containing
only its profile, loopback endpoint and trusted account/case/conversation/sender
bindings with an operation bearer. Native publishers can use this client without
inventing SMS provider metadata. The existing two-argument starter configuration
remains supported. Both paths keep two actual calls, strict original canonical
input checks and retained socket ownership through timeout/close.

The Python origin bridge is tracked in the active
[0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md).
Focused TypeScript and Python unit/socket checks passed. Fourteen actual
PostgreSQL assertions qualified P2 intake to P1 policy work and current result
data reads; the integrated native/voice/SMS journey remains pending. A prepared input's kind or receipt alone does not prove its source channel.

## Installed standalone starter

The additive ./starter application export and p2-channel-starter bin compose the
existing SDK with explicit owner/runtime configuration, signed fake SMS, the
reference case authority and an application-owned synthetic external receipt
server. Route an accepted structured investigation while quiescent before serving;
reply, callback and original-operation recovery remain explicit commands. No P1/P3
deployment, model, new workflow queue or default service is started.

See [STARTER.md](STARTER.md) for private configuration, commands, bounds and shutdown.
The [0041 work item](../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records source-bound qualification and remaining release requirements. The existing
operations page remains read-only.
