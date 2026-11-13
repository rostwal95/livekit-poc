# Installed channel starter

Status: Active
Last reviewed: 12 November 2026

## Purpose

The starter composes the public Channel Continuity Kit as one explicitly configured
local application. It uses the standalone reference case authority, signed fake SMS,
the existing persisted gateway/dispatcher and explicit reply, callback and recovery
commands. It requires PostgreSQL; it starts no P1/P3 deployment, model, room or
supplier worker. The [0041 work item](../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records observed qualification and remaining integration work.

The public application entry is ./starter. The p2-channel-starter executable is a
thin wrapper over the same factory. Import and plan perform no setup. Owner bootstrap,
external receipt serving and gateway serving are separate explicit commands. Normal
restart uses the same configured schemas and preserves accepted identities.

## Components

| Component | Owns | Does not establish |
| --- | --- | --- |
| Existing P2 inbox and dispatcher | Original accepted inputs, operation keys, prepared investigations and persisted eligible dispatch | Exact quote confirmation or supplier mutation |
| Reference case authority | Synthetic request revision and investigation-consent CAS | A second copy of a P1 case |
| Application fake external server | Bounded immutable synthetic investigation/provider receipts | A workflow queue, retry scheduler, real SMS delivery or business completion |
| Explicit outbox and callback commands | Immutable reply/send attempts, separate provider reports and original recovery commands | Playback, hearing or human acknowledgement |
| Public starter factory | Runtime construction, one command owner, session mode mutex and dependent shutdown | Another execution owner or fleet capacity |

The fake external schema has four tables: receipt_metadata,
investigation_receipts, idempotent_sms_receipts and ordinary_sms_attempts. Its
version is separate from existing inbox v7 and reference-case v1. Runtime can
append/read receipts and update three bounded admission counters; owner-installed
profile, catalog and definition data remain protected. Equal investigation or
idempotent-operation replay and changed-content conflict are resolved before
capacity rejection. Ordinary sends append a distinct physical-call observation on
every invocation, including an equal attempt/key. They expose no reliable lookup
or automatic resend permission. No accepted identity is evicted to regain capacity.

The investigation wire sends canonicalPayload once, plus its digest and version;
the server reconstructs and checks every original submission field. A 32 KiB wire
and canonical-text bound covers the existing empty/4 KiB message domain, including
JSON escaping and maximum identifiers. Ordinary reply text remains nonempty.
Header/response limits stay 4 KiB, with eight sockets, four handlers, two actual
receipt calls and one external SQL connection. These are bounded profile limits,
not measured throughput or per-case/fleet capacity.

## Configuration

Prepare trusted files in a canonical private directory owned by the launching user
(mode 0700), with regular exclusive files at mode 0600. The reader rejects symlinks,
hardlinks, unsafe permissions, duplicate JSON keys, invalid UTF-8 and oversized files.
It reads no ambient provider environment, credentials, proxy, executable or module
selector. Credentials belong in these private files, never command arguments, URLs,
metrics or captured output.

| File | Required fields and binding |
| --- | --- |
| Configuration | schemaVersion:1; profileId UUIDv4; postgres with literal 127.0.0.1, port and livekit_lab; inbox/case/external schema names; configured bindings; two loopback ports; fixed limits |
| Each binding | alias, providerScope, accountScope, caseId, conversationId, senderId, initialCase with revision "0" and a strict investigation request |
| Owner credentials | role:owner, matching profileId and continuity_migrator password; no runtime tokens |
| Runtime credentials | role:runtime, matching profileId and livekit_lab password; alias-bound account/publisher/recovery tokens, distinct fake-provider/callback HMAC keys and external-port bearers |
| External credentials | role:external, matching profileId and livekit_lab password; distinct alias-bound operation/ordinary/idempotent bearers; no account or confirmation capability |

The supported starter profile binds one case/conversation per account and one fake
provider tuple, with at most sixty-four configured accounts and a 16 KiB configuration
file bound. Initial revision 0 is a valid read. An explicit accepted structured
investigation must route to a positive revision before gateway startup. Bootstrap
never silently promotes it. This does not add native execution at revision 0.

Schema names are p2_inbox_ plus the owned thirty-two-character hexadecimal suffix,
p2_case_ plus that suffix, and p2_demo_ plus that suffix. Runtime never creates or
repairs these schemas. Owner bootstrap validates an existing installation; it does
not reset data or rewrite a changed baseline.

External bearers use forty-three base64url characters. Pass their full Bearer header
to the existing typed carrier clients. HMAC keys encode thirty-two bytes canonically
as base64url. Account, publisher, recovery and external capabilities are distinct.
A request-body tenant/account/case value only correlates with a verified binding.

### Operation-only client construction

The public `./starter` exports include `OperationClientConfig` and
`OperationClientBinding`. `new ExternalOperationClient(config)` accepts a version-1
profile UUID, literal loopback endpoint and one to sixty-four trusted bindings.
Each binding supplies alias, accountScope, caseId, conversationId, senderId and a
43-character operation bearer. Aliases and account scopes must be unique. It
copies and validates configuration before ownership transfer and needs no SMS
provider/recipient configuration. Native publishers can use the same accept,
lookup and preflight contract without inventing provider identities.

The existing `new ExternalOperationClient(starterConfig, credentials)` form is
supported. Both forms retain two actual calls and their sockets until settlement;
close can report incomplete and be retried. An HTTP accept failure is conservatively
`OutcomeUnknown`; a failed lookup is `Unavailable`. Do not infer a definitive
business denial from these transport observations or resubmit under a new key.

## Commands

From the repository, build using the pinned toolchain before testing its artifact:

```sh
corepack pnpm --filter @livekit-ecosystem/channel-continuity build
make p2-standalone-plan
```

An isolated installation exposes p2-channel-starter. These examples use paths to
already prepared private files; they contain no password or signing key values.
Create a new private output path for each observation; overwriting facts is rejected.

```sh
p2-channel-starter plan
p2-channel-starter bootstrap --config /private/tmp/starter/config.json --credentials /private/tmp/starter/owner.json
p2-channel-starter challenge --config /private/tmp/starter/config.json --credentials /private/tmp/starter/runtime.json --input /private/tmp/starter/challenge-request.json --output /private/tmp/starter/challenge-proof.json
p2-channel-starter associate --config /private/tmp/starter/config.json --credentials /private/tmp/starter/runtime.json --input /private/tmp/starter/signed-link.json
p2-channel-starter accept --config /private/tmp/starter/config.json --credentials /private/tmp/starter/runtime.json --input /private/tmp/starter/signed-request.json --output /private/tmp/starter/accepted.json
p2-channel-starter route --config /private/tmp/starter/config.json --credentials /private/tmp/starter/runtime.json --input /private/tmp/starter/route-original-receipt.json --output /private/tmp/starter/route-result.json
p2-channel-starter external --config /private/tmp/starter/config.json --credentials /private/tmp/starter/external.json --ready /private/tmp/starter/external-ready.json
p2-channel-starter serve --config /private/tmp/starter/config.json --credentials /private/tmp/starter/runtime.json --ready /private/tmp/starter/gateway-ready.json
```

Run the two long-lived commands in separately owned terminals/processes. A gateway
startup first observes the configured external profile and current reference case,
then binds. Explicit dispatch and lookup-only dispatch reconciliation also observe
the configured profile before constructing their SDK dispatcher. That readiness observation is as of those reads, not a guarantee that
a later external call succeeds. Missing/wrong-profile/authenticated-port failure
stays explicit. History and inspection remain usable when the external server is
down.

The route command changes the investigation request through CAS. select-route
separately selects an outbound sender/association epoch. All explicit mutating
application commands require a quiescent gateway: stop the owned serving process
before association, acceptance, routing, explicit dispatch, reply/send, callback or
recovery commands. Ordinary inbound acceptance while serving still uses the
existing gateway. Reads remain available. The application holds one PostgreSQL
session advisory mutex across mutating commands or live gateway serving, including
actual dependent closure. A second serve or routing process fails ApplicationBusy;
a TCP precheck is not its exclusion mechanism. This mutex is not a durable lease,
work queue or fence against arbitrary independent case actors. No transaction spans
external HTTP. A lost revision acknowledgement remains unknown; matching later state
does not identify the original winning command and authorizes no automatic retry.

| Command input | Meaning |
| --- | --- |
| challenge {bindingAlias} | Create the actual bounded association challenge; its secret is written only to the required private output |
| associate / accept / callback {raw,headers} | Preserve exact signed UTF-8 wire text and timestamp/signature; LINK proof establishes association separately from business acceptance |
| route {bindingAlias,receiptId} | Route only the original authenticated accepted structured input while quiescent |
| inspect / processing {bindingAlias,receiptId} | Read the complete original input or current durable dispatch observation |
| case {bindingAlias} | Read the separately observed current synthetic case |
| history {bindingAlias,after,limit} | Page immutable accepted rows by decimal sequence; limit 1–8, with a separate 64 KiB output bound |
| reply {bindingAlias,draft} | Accept one immutable reply; it does not send automatically |
| select-route {bindingAlias,senderId,associationVersion,expectedRouteVersion} | Explicitly select the current verified outbound route |
| send / inspect-reply {bindingAlias,outboundId,capability} | Use the selected ordinary_fake_sms_v1 or idempotent_fake_sms_v1 capability without fallback |
| inspect-callbacks {bindingAlias,outboundId,attemptId} | Inspect independent signed delivery reports for the original attempt |
| reconcile {bindingAlias,capability,commandId,outboundId,attemptId} | Explicit original-operation lookup/policy decision |
| retry {bindingAlias,capability,commandId,outboundId,expectedAttemptId} | Explicit guarded retry decision; ordinary unknown sends do not gain resend permission |

A sender text such as yes, a delivery report, a successful lookup or an operation
receipt grants no quote/confirmation or supplier authority. The existing operations
page remains a separate read-only composition; this CLI adds no mutation endpoint
to it.

## Observation and shutdown

CLI stdout is a bounded body-free typed summary. Optional private output retains
complete public facts without truncating records or UTF-8. Read-only observations
remain as of their separate reads; acceptance-row cursors are not a complete status
event feed. A send/dispatch uncertainty remains explicit. A known recovery receipt
and its separate provider observation do not rewrite the original lost send ACK.
An ordinary unknown result can coexist with a signed delivered callback.

The three existing carrier HTTP routes keep their immutable public-client header
contract: authenticated POST-only literal loopback and Connection close, without
Cache-Control. New investigation/profile routes use no-store. No proxy or cache
service is introduced.

Stop only the actually launched owned process with SIGINT or SIGTERM. It closes
dependent gateway/dispatcher/read owners before shared case, transport and mutex
resources. Caller timeout or abort does not prove underlying work stopped. Repeated
close observations share one actual pass; unfinished owners remain visible and
prevent a replacement mode from acquiring the mutex. Retain marked work and the
first failure when cleanup is incomplete. This CLI provides no reset, schema drop,
arbitrary PID, automatic resend or background recovery command.

## Validation and limits

The [bounded manifest](starter/bounded-v1.json) declares the twenty installed
standalone groups and the premeasurement process/output/resource limits. The
explicit local gate is make p2-standalone-check. Its standalone application uses no
P1/P3 service. A separately reported six-check installed P1 contract composition
repeats public revision/confirmation/current-fact boundaries; those checks do not
make P1 a prerequisite of the twenty or add a P1 operation bridge.

The isolated consumer must use the actual archive, public application export and
bin, with no repository imports or undeclared driver type dependency. Actual
PostgreSQL proves replay/conflict-before-capacity, restricted metadata privileges,
mode exclusion, original identities through owned process failure and populated
restore. Controlled loopback/mocked-owner tests qualify their stated boundaries
separately. Selected task results do not establish native/media or complete charter
release. I22 owns fresh-agent, supported-platform and integrated release evidence.
