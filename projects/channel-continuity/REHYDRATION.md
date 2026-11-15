# Current-case rehydration contract

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the opt-in I18 read-only current-case context profile for returning interactions |
| Audience | Engineers who compose or change the P2 rehydration profile; coding agents |
| Scope | The `./rehydration` export and `channel_continuity.native_rehydration`; excludes acceptance, generation and mutation |
| Owns | Current-grant admission, raw SMS read authentication, history and P1 fact composition, byte and page bounds, explicit refresh and room identity |
| Related | [Project guide](README.md) · [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) · [Communication contract](COMMUNICATION.md) · [Python adapter](python/README.md) |

## Overview

This contract describes the opt-in I18 read-only current-case profile: the
TypeScript `./rehydration` export and the Python
`channel_continuity.native_rehydration` module.

The `./rehydration` export assembles a bounded current-case read and retained P2
source facts for an authenticated returning interaction. Existing P1 and P2 state
remains the authority.

| Capability | Status | Evidence |
| --- | --- | --- |
| I18 read-only current-case profile | Qualified | [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| Integrated native revision-0 coverage | Planned | [Revision zero](#revision-zero) |
| Full charter coverage | Planned | [V1 charter](../../docs/projects/channel-continuity-scope.md) |

- Loading context creates no input, prepared plan, operation, quote, confirmation,
  carrier send or software development kit (SDK) generation.
- The I18 handoff records qualification and remaining integration boundaries.

## Authority and composition

### Constructing the rehydrator

Construct `ChannelRehydrator(inboxOrGateway, currentCasePort, fakeSmsIntegration)`
with a real native/communication inbox or gateway.

- Its package-internal read capability reuses that inbox's pool, admission lock and
  validated native and communication readers.
- The facade adds no SQL pool, persisted summary, scheduler or execution owner.
- Applications separately own the inbox or gateway, the current-case adapter and the
  explicit `RehydrationHttpServer`.

### Native and SMS reads

| Read | Scope source |
| --- | --- |
| `native(bindingBearer, query?, signal?)` | Derives account, case, conversation, room and participant from the original current grant |
| `sms(raw, headers, query?, signal?)` | Authenticates exact raw fake-SMS v1 bytes; requires the original already accepted event plus the same current sender association epoch |

- The configured SMS provider capability stays separate from native LiveKit
  authority.
- Neither read accepts a caller-constructed principal, receipt, provider or case
  selector.
- SMS acceptance is a separate prior application action. The read never calls
  `acceptSms`.

### Read sequence

1. A coherent P2 repeatable-read transaction captures bounded original rows.
2. The facade releases SQL before one external `CurrentCasePort.inspect`.
3. A new protected transaction acquires existing admission and original grant/head
   locks. It rechecks current authorization and fresh PostgreSQL time, and admits
   disclosure. SMS hash-based message authentication code (HMAC) freshness is
   checked again after locks.

Consequences of this sequence:

- A revocation or expiry that wins before the last check denies the read.
- A revocation after admitted disclosure cannot retract bytes already returned.
- P1 and P2 are separately observed. `observed.atomic` is always false.
- No database transaction remains open over network I/O.

### Current-case allowlist

`CurrentCase` has an explicit allowlist: request revision, investigation request,
source-qualified workflow/intent/mutation/outcome references and actual mutation
supplier result.

- Integrated mode uses one public P1 `ManagedCaseClient.get` through a fixed
  trusted mapping.
- Quote and confirmation payloads, nonces, tools, commands and private controls are
  excluded.
- Inquiry availability never becomes supplier mutation truth.
- Standalone mode reads the existing reference-case authority instead of a P1 state
  clone.
- A projection fingerprint is distinct from case and supplier revisions.

## Read model and bounds

### Envelope and context fields

The known HTTP envelope has `schemaVersion`, `status:known` and `context`. The
context has exactly nine fields: `schemaVersion`, `contextId`, `access`, `case`,
`history`, `work`, `responses`, `replies` and `observed`. The fresh context UUID
identifies an observation, not a durable receipt or execution capability.

### Section budgets

| Section | Meaning | Maximum records | UTF-8 JSON section budget |
| --- | --- | --- | --- |
| case | Validated authority-derived current-case observation | 1 | 4096 bytes |
| history | Original accepted messages/receipts/operation identities across verified providers | 8 | 28672 bytes |
| work | Persisted pending/running/blocked/uncertain/exhausted references; no eligibility promise | 8 | 4096 bytes |
| responses | Original inert response/generation/speech references and source summaries, no generated text | 4 | 12288 bytes |
| replies | Original queued reply/attempt references and at most four callback summaries | 4 | 8192 bytes |

The complete serialized JSON envelope, including metadata and cursors, is at most
65536 UTF-8 bytes.

### Paging and cursors

- Records are omitted whole, with explicit section continuation. Canonical bodies
  and source facts are never truncated or rewritten.
- History and work page by original conversation acceptance sequence. Response
  history pages by its scoped response sequence. Replies page by accepted time plus
  UUID.
- Each cursor includes the server-derived scope digest and is a paging hint, not
  authority.
- Each request is a fresh observation. Pages are not one cross-request snapshot.
- The P1 fingerprint is not any P2 cursor.

### Identifier bounds and storage

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Booking reference | 64 UTF-8 bytes | Current-case booking references | Canonical control-free subset; unsupported wider P1 values fail unavailable without rewriting |
| Task identity | 128 Unicode codepoints, at most 512 UTF-8 bytes | Trusted P1 task identity | None |

- Native, account, case and control identifiers preserve their existing ASCII
  contracts.
- Existing v7 storage needs no new migration, cache, tombstone or canonical-row
  edit.

### Facade concurrency and deadlines

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual calls | 2 | Facade | Retained after caller timeout or abort |
| Deadline | 3 seconds (default) | Each read | Maximum 5 seconds |
| SQL capacity | The existing four SQL operations and two connections | Shared inbox pool | No new pool |
| Close wait | 5 seconds | Close | At most |
| Pending observer promises | 8 | Observers | At most |

- Close reports incomplete ownership honestly.
- Observers use finite events and codes. No transcript, identifier or credential is
  a metric label.
- Fixed counts distinguish known reads, denied or unavailable reads, overload and
  abandoned waiters.

### Loopback HTTP server bounds

The explicitly started loopback HTTP server has these bounds:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Headers | 4096 bytes | Each request | None |
| Native request JSON | 4096 bytes | Each native request | None |
| SMS envelope | 49152 bytes | Each SMS request | None |
| Response JSON | 65536 bytes | Each response | None |
| Handlers | 2 | Server | None |
| Sockets | 16 | Server | None |

- The server requires exact framing, the original native bearer and the actual
  bound `Host` port.
- Imports start no listener and no remote provider call.

## Native Python profile

### Loading context into the SDK

`channel_continuity.native_rehydration` contains pure models,
`NativeContextHttpClient` and `NativeRehydrationProfile` without importing Agents.
With the optional pinned SDK, pass `rehydration=NativeRehydrationProfile(port)` to
`NativeRuntime`.

- The profile loads validated context through public `Agent.update_chat_ctx` before
  RoomIO readiness.
- Original accepted-history IDs remain stable.
- Old response summaries are inert source data. They never enter the new room's
  response, interrupt or playback registry.
- Loading and explicit idle `refresh_context()` perform zero acceptance or
  generation.
- A held context load retains its actual task through timeout and close.

### As-of facts and revision guards

The SDK data includes observation times and the source fingerprint.

- Workflow, supplier or delivery state may advance without changing the request
  revision. Answers must qualify those facts as of the observation and use an
  explicit refresh for current outcome questions.
- Prepare revision equality protects only the investigation revision. It does not
  protect live supplier freshness or cross-authority atomicity.
- A mismatch fails before SDK generation rather than silently rebasing the accepted
  input or prepared plan.

### Revision zero

- `CurrentCase` can read revision zero, including public P1's initial case.
- Existing native dispatch and communication still require a positive revision.
- The optional profile rejects new native input at loaded revision zero before
  durable acceptance. It never maps zero to one or revises the case automatically.
- Selected native media uses an explicitly verified revision-one reference case and
  a separate real compare-and-set (CAS) to two.
- Full valid-domain integrated native qualification requires later versioned
  zero-revision compatibility before release.

### New rooms and old-room history

- A new room uses a new trusted binding and fresh IDs for genuinely new input.
- Old room input is displayed with its original sender and receipt. Replaying it
  under a new binding would conflict.
- Disconnect alone does not revoke or renew grants or cancel committed work.
- Late old-room context cannot overwrite the active new-room view. Old response IDs
  cannot become new-room speech controls.
- The existing eighteen native metrics, acknowledgement (ACK) and generation wire
  remain closed. Context metrics and readiness are opt-in.

## Validation and evidence

Keep schema/model and actual loopback tests separate from real PostgreSQL, process
termination, restored state, browser/audio and installed-artifact evidence.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Schema/model and actual loopback tests | Package and Python unit commands in the [project guide](README.md#commands) | Pure models and loopback behavior | Passed (0038) |
| Storage lane | `make p2-rehydration-check` | Scope, permissions, P1 normalization, paging, retained I/O, expiry and replay against real PostgreSQL | Passed (0038) |
| Media lane | `make p2-rehydration-media-check` | Room A voice and chat, then a fresh room B that loads context before new input | Passed (0038) |
| Isolated Python distribution and npm consumer | Recorded in the [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) | Installed artifacts outside the checkout | Passed (0038) |
| P2 compatibility | Recorded in the [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) | Selected earlier P2 assertions still pass | Passed (0038) |

- The storage lane covers original native/SMS scope, exact current permissions,
  read-only P1 source normalization, same-case source changes, concurrent append,
  per-section paging and bytes, retained I/O, expiry behind a real admission lock
  and fresh replay.
- The media lane uses actual voice and chat in room A, room closure, a fixed signed
  fake SMS and a fresh room B whose context loads before new input.

Neither a context read, SDK completion nor client playback grants mutation consent,
physical hearing or delivery, or complete P2 charter acceptance.

### Selected qualification results

| Proof | Observed result |
| --- | --- |
| Storage | Eighteen assertions passed in 6.534 seconds |
| Media | Three actual media groups passed in one Playwright case in 35.797 seconds |
| Isolated Python distribution | 111 tests, nine payloads and fifteen commands passed |
| Isolated npm consumer | Seven stages passed, with original-fact fresh replay and zero new read side effects |
| P2 compatibility | All 166 selected assertions passed in 98.997 seconds |

P2-I19 and P2-I20 have since passed their selected gates, recorded in
[0039](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
and [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
Full charter and integrated native revision-0 coverage remain separately gated.
These results add no hearing, consent or physical delivery claim.
