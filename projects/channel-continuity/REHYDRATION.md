# Current-case rehydration contract

Status: Active
Last reviewed: 11 November 2026

The opt-in `./rehydration` export assembles a bounded current-case read and retained
P2 source facts for an authenticated returning interaction. Qualification and
remaining integration boundaries are recorded in the [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).
Loading context creates no input, prepared plan, operation, quote, confirmation,
carrier send or SDK generation. Existing P1/P2 state remains the authority.

## Authority and composition

Construct `ChannelRehydrator(inboxOrGateway, currentCasePort, fakeSmsIntegration)`
with a real native/communication inbox or gateway. Its package-internal read
capability reuses that inbox's pool, admission lock and validated native and
communication readers. The facade adds no SQL pool, persisted summary, scheduler
or execution owner. Applications separately own the inbox/gateway, current-case
adapter and explicit `RehydrationHttpServer`.

`native(bindingBearer, query?, signal?)` derives account, case, conversation, room
and participant from the original current grant. `sms(raw, headers, query?, signal?)`
authenticates exact raw fake-SMS v1 bytes and requires the original already accepted
event plus the same current sender association epoch. The configured SMS provider
capability stays separate from native LiveKit authority. Neither read accepts a
caller-constructed principal, receipt, provider or case selector. SMS acceptance
is a separate prior application action; the read never calls `acceptSms`.

A coherent P2 repeatable-read transaction captures bounded original rows, then
releases SQL before one external `CurrentCasePort.inspect`. A new protected
transaction acquires existing admission and original grant/head locks, rechecks
current authorization and fresh PostgreSQL time, and admits disclosure. SMS HMAC
freshness is checked again after locks. Revocation/expiry that wins before this
last check denies the read. Revocation after admitted disclosure cannot retract
bytes already returned. P1 and P2 are separately observed; `observed.atomic` is
always false. No database transaction remains open over network I/O.

CurrentCase has an explicit allowlist: request revision, investigation request,
source-qualified workflow/intent/mutation/outcome references and actual mutation
supplier result. Integrated mode uses one public P1 `ManagedCaseClient.get` through
a fixed trusted mapping. Quote/confirmation payloads, nonces, tools, commands and
private controls are excluded. Inquiry availability never becomes supplier mutation
truth. Standalone mode reads the existing reference-case authority instead of a
P1 state clone. A projection fingerprint is distinct from case and supplier revisions.

## Read model and bounds

The known HTTP envelope has `schemaVersion`, `status:known` and `context`. Context
has exactly nine fields: `schemaVersion`, `contextId`, `access`, `case`, `history`,
`work`, `responses`, `replies`, `observed`. The fresh context UUID identifies an
observation, not a durable receipt or execution capability.

| Section | Meaning | Maximum records | UTF-8 JSON section budget |
| --- | --- | --- | --- |
| case | Validated authority-derived current-case observation | 1 | 4096 bytes |
| history | Original accepted messages/receipts/operation identities across verified providers | 8 | 28672 bytes |
| work | Persisted pending/running/blocked/uncertain/exhausted references; no eligibility promise | 8 | 4096 bytes |
| responses | Original inert response/generation/speech references and source summaries, no generated text | 4 | 12288 bytes |
| replies | Original queued reply/attempt references and at most four callback summaries | 4 | 8192 bytes |

The complete serialized JSON envelope, including metadata and cursors, is at most
65536 UTF-8 bytes. Records are omitted whole with explicit section continuation;
canonical bodies and source facts are never truncated or rewritten. History/work
page by original conversation acceptance sequence, response history by its scoped
response sequence, replies by accepted time plus UUID. Each cursor includes the
server-derived scope digest and is a paging hint, not authority. Each request is
a fresh observation; pages are not one cross-request snapshot. The P1 fingerprint
is not any P2 cursor.

Current-case booking references use a canonical control-free 64 UTF-8 byte subset;
unsupported wider P1 values fail unavailable without rewriting. Trusted P1 task
identity supports 128 Unicode codepoints, at most 512 UTF-8 bytes. Native/account/
case/control identifiers preserve their existing ASCII contracts. Existing v7
storage needs no new migration, cache, tombstone or canonical-row edit.

The facade retains two actual calls after caller timeout/abort, uses a three-second
default deadline (maximum five), and shares the existing four SQL operations/two
connections. Close waits at most five seconds and reports incomplete ownership
honestly. Observers use finite events/codes with at most eight pending promises;
no transcript, identifier or credential is a metric label. Fixed counts distinguish
known reads, denied/unavailable reads, overload and abandoned waiters.

The explicitly started loopback HTTP server bounds headers to 4096 bytes, native
request JSON to 4096, SMS envelope to 49152, response JSON to 65536, handlers to two
and sockets to sixteen. It requires exact framing, original native bearer and
actual bound Host port. Imports start no listener and no remote provider call.

## Native Python profile

`channel_continuity.native_rehydration` contains pure models, `NativeContextHttpClient`
and `NativeRehydrationProfile` without importing Agents. With the optional pinned
SDK, pass `rehydration=NativeRehydrationProfile(port)` to `NativeRuntime`. It loads
validated context through public `Agent.update_chat_ctx` before RoomIO readiness.
Original accepted-history IDs remain stable. Old response summaries are inert
source data and never enter the new room's response/interrupt/playback registry.
Loading and explicit idle `refresh_context()` perform zero acceptance/generation.
A held context load retains its actual task through timeout and close.

The SDK data includes observation times and source fingerprint. Workflow, supplier
or delivery state may advance without changing the request revision; answers must
qualify those facts as of the observation and use an explicit refresh for current
outcome questions. Prepare revision equality protects only investigation revision,
not live supplier freshness or cross-authority atomicity. A mismatch fails before
SDK generation rather than silently rebasing the accepted input or prepared plan.

CurrentCase can read revision zero, including public P1's initial case. Existing
native dispatch and communication still require a positive revision. The optional
profile rejects new native input at loaded revision zero before durable acceptance;
it never maps zero to one or revises the case automatically. Selected native media
uses an explicitly verified revision-one reference case and a separate real CAS to
two. Full valid-domain integrated native qualification requires later versioned
zero-revision compatibility before release.

A new room uses a new trusted binding and fresh IDs for genuinely new input. Old
room input is displayed with its original sender/receipt; replaying it under a new
binding would conflict. Disconnect alone does not revoke/renew grants or cancel
committed work. Late old-room context cannot overwrite the active new-room view;
old response IDs cannot become new-room speech controls. Existing native eighteen
metrics, ACK and generation wire remain closed; context metrics/readiness are opt-in.

## Verification

Keep schema/model and actual loopback tests separate from real PostgreSQL,
process termination, restored state, browser/audio and installed-artifact evidence.
The storage lane covers original native/SMS scope, exact current permissions,
read-only P1 source normalization, same-case source changes, concurrent append,
per-section paging/bytes, retained I/O, expiry behind a real admission lock and
fresh replay. The media lane uses actual voice/chat in room A, room closure,
fixed signed fake SMS and a fresh room B whose context loads before new input.
Neither a context read, SDK completion nor client playback grants mutation consent,
physical hearing/delivery or complete P2 charter acceptance.


Selected qualification passed eighteen storage assertions in 6.534 seconds and
three actual media groups in one Playwright case in 35.797 seconds. The isolated
Python distribution passed 111 tests/nine payloads/fifteen commands; the npm
consumer passed seven stages with original-fact fresh replay and zero new read
side effects. All 166 selected P2 compatibility assertions passed in 98.997 seconds.
P2-I19/I20 are next. Full charter and integrated native revision-0 coverage remain
separately gated; these results add no hearing, consent or physical delivery claim.
