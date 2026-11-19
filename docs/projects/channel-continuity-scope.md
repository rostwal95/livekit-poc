# Channel Continuity Kit scope

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the required V1 behavior and stable acceptance IDs for P2, Channel Continuity Kit |
| Audience | Engineers and coding agents who change P2 or check what its release requires |
| Scope | P2 behavior, contracts, acceptance matrix and release gates; excludes shared portfolio policy and evidence rules |
| Owns | P2 requirements and stable acceptance IDs |
| Related | [Portfolio scope](../portfolio-scope.md) · [Validation plan](../validation-plan.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P2 README](../../projects/channel-continuity/README.md) · [P2 design](../../projects/channel-continuity/Design.md) |

## Overview

This charter defines the required V1 behavior and the stable acceptance IDs for
P2, Channel Continuity Kit. It is for engineers and coding agents who change P2 or
need to check what its release requires. This charter is authoritative for P2
behavior and acceptance IDs. The [portfolio scope](../portfolio-scope.md) defines
shared boundaries, and the [validation plan](../validation-plan.md) defines
evidence.

### What P2 provides

Build a TypeScript SDK and gateway that preserve a synthetic travel-support case
across LiveKit voice, browser text and asynchronous SMS interactions. A new
interaction can load the current case and relevant communication history without
keeping a room or an agent process alive for every dormant conversation.

Continuity accounts for interrupted output. These remain separate observations:

- generated text;
- reported playback;
- provider delivery;
- explicit user acknowledgement.

### Terms used in this charter

| Term | Meaning |
| --- | --- |
| Implementation task IDs | IDs such as P2-I10 that identify work items in the [P2 implementation plan](../implementation/p2-channel-continuity.md); not acceptance IDs such as P2-10 |
| Selected qualification | The gates chosen for one work item passed within that item's declared local scope; it never completes a full acceptance row by itself |
| Acknowledgement (ACK) | A receiver's confirmation that it accepted a message or command; a lost ACK leaves the outcome unknown |
| Compare-and-set (CAS) | A write that succeeds only when the stored revision still matches the expected revision |

## Implementation status

P2 is partially implemented through implementation tasks P2-I01 to P2-I21 and the
P2-I22 origin-binding prerequisite in work item 0044. Each task's handoff records
its exact qualification boundary. All seventeen complete acceptance rows remain
planned and unregistered until every required assertion passes.

| Capability | Status | Evidence |
| --- | --- | --- |
| Versioned event contracts with parity fixtures (P2-I01, P2-I02) | Qualified | [0022](../work-items/0022-p2-channel-contracts.md) |
| Signed fake-SMS verification, seeded association and PostgreSQL inbox (P2-I03 to P2-I05) | Qualified | [0024](../work-items/0024-p2-verified-durable-intake.md) · [0026](../work-items/0026-p2-postgres-inbox.md) |
| Standalone fake-carrier example and read-only preview (P2-I06) | Qualified | [0027](../work-items/0027-p2-standalone-and-p3-http.md) |
| Owner v1-to-v2 upgrade and bounded investigation dispatch (P2-I07) | Qualified | [0028](../work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| Bounded loopback gateway with restart recovery (P2-I08) | Qualified | [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| Trusted agent-process adapter and worker protocol (P2-I09) | Qualified | [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| Revision routing over one selected case authority (P2-I10) | Qualified | [0031](../work-items/0031-revision-routing-and-delegation-acceptance.md) |
| Linked exact confirmation (P2-I11) | Qualified | [0032](../work-items/0032-linked-confirmation-and-result-projections.md) |
| Immutable outbound replies (P2-I12) | Qualified | [0033](../work-items/0033-outbound-replies-and-completion-processing.md) |
| Correlated callbacks (P2-I13) | Qualified | [0034](../work-items/0034-callback-evidence-and-applicability-refresh.md) |
| Explicit uncertain-send recovery (P2-I14) | Qualified | [0035](../work-items/0035-send-policy-and-action-races.md) |
| Native text and voice (P2-I15, P2-I16) | Qualified | [0036](../work-items/0036-native-input-and-deadline-cancellation.md) |
| Scoped playback evidence (P2-I17) | Qualified | [0037](../work-items/0037-playback-evidence-and-process-recovery.md) |
| Scoped current-case context (P2-I18) | Qualified | [0038](../work-items/0038-case-rehydration-and-standalone-release.md) |
| Bounded workload studies (P2-I19) | Qualified | [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| Read-only operations UI and telemetry (P2-I20) | Qualified | [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| Installed standalone release and public-P1 assertions (P2-I21) | Qualified | [0041](../work-items/0041-standalone-channel-and-durable-policy.md) |
| Receiver and current-channel data-read seam (P2 v8) | Qualified | [0043](../work-items/0043-stable-result-delivery-and-return-context.md) |
| Original P2-input binding prerequisite for P2-I22 | Qualified | [0044](../work-items/0044-origin-bound-channel-policy.md) |
| Release and joined native voice/text/SMS handoff (P2-I22) | Partial: joined qualification and restart/release gates remain open | [P2 task plan](../implementation/p2-channel-continuity.md) · [Joined application](../work-items/0045-joined-native-channel-policy.md) |
| All seventeen complete acceptance rows | Planned | Acceptance matrix below |

### Contracts, intake and dispatch (P2-I01 to P2-I09)

- **P2-I01 and P2-I02** implement versioned TypeScript and Python event contracts
  with producer/decoder parity fixtures. This first slice is recorded in the
  [contract work item](../work-items/0022-p2-channel-contracts.md), which retains
  its original scope.
- **P2-I03, P2-I04 and P2-I05** add signed fake-SMS verification, seeded
  association, and a PostgreSQL inbox with receipts and pending processing intent.
- **P2-I06** adds a standalone public-export fake-carrier example with a separate
  read-only preview. Its operation observation explicitly remains `not_executed`
  only while input is pending.
- **P2-I07** adds an explicit owner v1-to-v2 upgrade and bounded, persisted
  investigation dispatch with lookup-only reconciliation.
  - The original prepared input and operation identity survive takeover.
  - Possible external acceptance remains uncertain until a matching
    cooperating-port receipt is observed.
  - A nonpending input cannot reuse the old `not_executed` preview.
- **P2-I08** adds an actual bounded loopback gateway with raw authenticated intake,
  persisted eligible selection, and recovery after accepted acknowledgement or
  process loss. It has no in-memory acceptance queue.
- **P2-I09** adds an explicit trusted agent-process adapter and worker protocol.
  - The live gateway can retain a committed message after independent
    scripted-worker death, observe claim expiry and reprocess the original
    immutable input, case and operation context.
  - Attempts are visible while cooperating operation acceptance stays one logical
    investigation.
  - Selected phase gates passed for this bounded I09 failure path.

### Revision routing (P2-I10)

P2-I10 adds explicit `RevisionRouter` and `CaseAuthorityPort` contracts over strict
structured investigation commands read from authenticated retained inbox input. A
deployment selects exactly one authority: the standalone reference PostgreSQL
authority or the integrated P1 loopback bridge.

Current case compare-and-set, stale conflict, clarification and unknown
acknowledgement stay distinct. The selected 22-case equivalent-authority gate
passed. Final phase and task qualification remains recorded in the
[routing work item](../work-items/0031-revision-routing-and-delegation-acceptance.md),
which retains its original scope.

### Later selected tasks (P2-I11 to P2-I20)

The status table lists the later selected tasks through P2-I20, from linked exact
confirmation (P2-I11) to the read-only operations UI (P2-I20). Their separate
handoffs retain exact qualification boundaries. The
[0040 handoff](../work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records the selected operations checkpoint.

No parser or canonical event grants account authority or proves persisted
acceptance.

### Standalone and result-return checkpoint (0040 to 0044)

- **Operations and telemetry (P2-I20).** P2-I20 read-only operations and telemetry
  retains its qualified
  [0040 handoff](../work-items/0040-operations-ui-and-fixed-policy-evidence.md).
- **Standalone release (P2-I21).** The completed
  [0041 handoff](../work-items/0041-standalone-channel-and-durable-policy.md)
  qualified P2-I21's twenty installed standalone assertions and six separate
  public-P1 assertions.
- **Native policy text (P3-I18B).** P3-I18B subsequently passed selected
  source/installed native real-time communication (RTC) text qualification in
  [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md). That
  separate application does not establish joined P2 voice/SMS routing.
- **Result return (0043).** The completed
  [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
  qualified the P2 v8 receiver/current-channel data-read seam and P3's v2 result
  delivery: sixteen storage and four return source assertions passed.
  - Its separate twenty-five-stage offline package lane qualifies isolated
    consumers. It is not an installed repetition of those twenty actual source
    assertions.
  - A current native grant data read does not establish RTC media or provider
    inference.
- **Original-input binding (0044).** The
  [0044 work item](../work-items/0044-origin-bound-channel-policy.md) implements
  the original P2-input binding, schema3 policy facades, a narrow operation client
  and a local application HTTP boundary.
  - Focused unit/socket checks and isolated package/fake-port qualification
    passed.
  - The fourteen-assertion actual source gate passed with complete cleanup.

### Remaining work and limits

- P2-I22's joined qualification, restart/discovery and release gates remain open.
  The later [provider journeys and recorded demo](../work-items/0046-joined-showcase-providers-and-demo.md)
  have their own evidence; they do not complete those gates.
- All seventeen complete P2 acceptance rows remain planned and unregistered. The
  catalog remains fifty-five definitions and twenty-four registered runners.

## Ownership and dependencies

### Owners

| Owner | Responsibility |
| --- | --- |
| TypeScript channel package | Versioned events, scoped identities, message acceptance, delivery semantics, case routing, adapter interfaces |
| TypeScript gateway | Provider verification, normalization, persisted inbox and outbox, retries, synthetic account association |
| Python LiveKit adapter | Loading scoped case context, routing accepted input into the agent, recording native conversation and interruption events |
| Browser client | Native LiveKit audio and text interaction, reconnect handling, clearly labelled client playback observations |
| Case store | Authoritative case revision and confirmed facts, separate from room identity and generated summaries |
| Project 1 integration | Durable business execution and supplier effects through a narrow operation port |

### Standalone and integrated use

This project does not own supplier execution, workflow recovery or specialist
scheduling. It can run independently using a small local case store, a scripted
agent adapter and a fake operation port.

| Dependency | Standalone use | Integrated use |
| --- | --- | --- |
| Project 1 | Not a required deployment for the standalone example | Integration adapter for durable business execution and supplier effects through a narrow operation port |
| Project 3 | Not a dependency | Not a dependency |

### Native LiveKit text, transcription and UI

Use LiveKit's existing `lk.chat` text input and hybrid/text-only session support.
Its synchronized output transcriptions already stop and truncate on interruption.
Consume that behavior rather than implementing a speech synchronizer. See
[text and transcriptions](https://docs.livekit.io/agents/multimodality/text/).

Evaluate the official Agents UI components when introducing the product
conversation client. Retain application-specific durable receipts and history
behind the continuity contract. The existing diagnostic console need not be
rewritten merely to add a framework.

Native text streams transport data between connected participants and do not
provide long-term message persistence. This SDK supplies the application history
and acceptance protocol needed by the reference case. See
[text streams](https://docs.livekit.io/transport/data/text-streams/).

## Required V1 behavior

1. **Typed intake.** Accept committed user text from browser chat and the fake SMS
   carrier through one typed intake contract. Interim speech transcripts are
   observations, not confirmed business commands.
2. **Acknowledge after commit.** Acknowledge an input as accepted only after its
   canonical payload, stable identity, destination and processing intent are
   committed. Browser inputs show pending, accepted and failed states. Sending a
   realtime stream alone is not an application acceptance acknowledgement.
3. **Recovery.** Recover accepted pending input after gateway or agent restart.
   Processing may run again. Stable operation identities prevent repeated
   acceptance of the same logical business work. Do not promise exactly one large
   language model (LLM) invocation.
4. **Scoped deduplication.** Deduplicate by tenant, provider, provider account and
   provider event identity.
   - Identical replay returns the original receipt.
   - Changed content under the same identity produces a conflict.
   - Two distinct messages containing "yes" remain distinct inputs.
   - Canonicalization includes the semantic event payload and stable destination.
     It excludes local receipt times, retry counters, transport signatures and other
     delivery-attempt metadata.
   - Preserve such metadata as observations, so that an ordinary provider retry
     cannot create a false conflict.
5. **Stable identifiers.** Preserve conversation, case, message, response and room
   identifiers. A case can span multiple rooms. An archived room is not the case's
   state store.
6. **Revision-checked case changes.** Use a transaction and expected case revision
   when changing confirmed case intent. Resolve competing voice and text commands
   explicitly. Arrival time or a carrier timestamp does not establish a universal
   order across channels.
7. **Linked commands.** Associate commands with the case revision and the prompt or
   response they answer when that information exists. A delayed confirmation for an
   older revision cannot silently confirm the latest request. An ambiguous SMS "yes"
   causes clarification. Do not invent a revision association from the current room.
8. **Verified association.** Provide a minimal, verified association flow for
   seeded synthetic accounts. Unassociated senders cannot access a case. Provider
   webhook verification and user account association are separate checks. Test
   tenant separation in all reads, writes, callbacks and routing paths.
9. **Outgoing notifications.** Persist outgoing notification intent with a stable
   message identity. Correlate callbacks, preserve attempt history, bound retries
   and represent ambiguous delivery. A provider that lacks idempotent sends cannot
   support a guarantee of one physical SMS delivery after an uncertain send outcome.
10. **Output evidence.** Record output evidence with its source and uncertainty.
    Distinguish generated response, SDK-reported progress or interruption,
    client-reported playback, carrier delivery or read reports, and explicit user
    acknowledgement. Missing evidence remains unknown. None of these events alone
    proves comprehension or grants permission for a booking mutation.
11. **Rehydration.** On reconnect or channel change, rehydrate authoritative case
    facts, relevant accepted messages, pending work references and communication
    evidence. A generated summary cannot override the case revision or supplier
    outcome.
12. **Examples.** Ship one independently runnable fake-carrier example and one
    integrated browser example using an actual local LiveKit server. The required
    path uses no LiveKit Cloud feature or real carrier account.

### Custom input handling

For browser text that can change case intent, custom input handling must persist
acceptance before dispatching to the agent. Do not also let a default automatic
reply path consume that same input and produce a second logical action.

For voice, record committed utterances and native output evidence. Require the
application's explicit confirmation contract before invoking business operations.

## Public contracts

### Intended SDK shape

The following is the intended custom SDK shape. These names are illustrative until
the contract checkpoint. They are not existing LiveKit SDK methods.

```ts
type ProviderScope = { tenantId: string; provider: string; providerAccountId: string };
type AccountScope = { tenantId: string; accountId: string };
type BaseEvent = {
  schemaVersion: 1;
  eventId: string;
  providerScope: ProviderScope;
  accountScope?: AccountScope;
  conversationId: string;
  caseId?: string;
  occurredAt?: string;
  receivedAt: string;
  causationId?: string;
};

type ChannelEvent = BaseEvent & (
  | { type: "text.received"; channel: "web_chat" | "sms" | "voice_transcript";
      messageId: string; senderId: string; body: string;
      expectedCaseRevision?: number; replyToResponseId?: string }
  | { type: "response.generated"; responseId: string; body: string }
  | { type: "playback.reported"; responseId: string;
      source: "agent_sdk" | "browser_client";
      state: "started" | "partial" | "completed" | "interrupted";
      playedText?: string }
  | { type: "delivery.reported"; messageId: string;
      state: "accepted_by_provider" | "delivered" | "failed" | "unknown" | "read_reported" }
  | { type: "user.acknowledged"; responseId: string; messageId: string }
);

interface ChannelContinuity {
  accept(input: ChannelEvent, principal: TrustedPrincipal): Promise<Receipt>;
  inspect(messageId: string, principal: TrustedPrincipal): Promise<MessageRecord>;
  history(conversationId: string, principal: TrustedPrincipal): Promise<HistoryPage>;
  enqueueReply(reply: ReplyIntent, principal: TrustedPrincipal): Promise<Receipt>;
}
```

### Data contracts and trusted principals

`TrustedPrincipal`, `Receipt`, `ReplyIntent`, `MessageRecord` and `HistoryPage` are
exported data contracts at the first codec checkpoint.

| Contract | Required behavior |
| --- | --- |
| `TrustedPrincipal` | Comes from a separately authenticated adapter; constructing or parsing one does not establish authentication |
| Event scope | Validated against the trusted principal or verified provider adapter; a caller cannot grant itself access by supplying a tenant ID |
| History | Bounded and paginated |
| Raw audio and video | Carried by LiveKit media tracks, not inserted into this text-event envelope |
| Event variants | Have their own payload schemas and retain ordering and provenance information without forcing every modality into a text message |

### Provider scope and account scope

| Contract | Required behavior |
| --- | --- |
| `ProviderScope` | Identifies a carrier or integration account and scopes provider-event deduplication; it does not identify or authorize the end user |
| `AccountScope` | Identifies the business account after verified association; only the trusted association service may attach it to inbound provider events |

An unassociated event cannot read a case merely because its provider account is
recognized.

### Outcomes

| Outcome | Required meaning |
| --- | --- |
| Accepted receipt | Durable intake committed; processing may still be pending |
| Duplicate receipt | Same scoped event and canonical payload; returns original logical identity |
| `IdentityConflict` | Same scoped event identity, different canonical payload; no replacement |
| `AssociationRequired` / `AccessDenied` | Identity or case access not established; no case disclosure |
| `RevisionConflict` / `ClarificationRequired` | Command cannot safely be applied to the requested case revision |
| `UnsupportedEventVersion` / `InvalidEvent` | Validation failed before acceptance |
| `Overloaded` | Input was not accepted; retry behavior and stable identity are documented |
| `OutcomeUnknown` | A send may have reached the provider; do not label it failed merely to retry |

## Correctness and failure boundaries

| Boundary | Required behavior | Notes |
| --- | --- | --- |
| Delivery evidence and replay horizons | An older callback cannot overwrite stronger later evidence without an explicit provider rule | Define replay horizons and tombstones before adding cleanup |
| Separate commitment boundaries | Message acceptance, case commitment, provider delivery and user acknowledgement stay separate | An uncertain send cannot be labelled failed merely to justify retry |
| Revision routing (P2-I10) | Scope, case and operation identity come from an authenticated retained inbox read | No association-revocation fence; a lost P1 revision ACK remains unknown |
| Verified association lifecycle | Challenges are consumed once and associations are versioned | P2-12 covers challenge, revocation and reassignment cases |
| Acceptance sequence and business causality | A server sequence orders accepted inputs within one tenant, account and conversation | Neither a global channel clock nor mutation authority; P2-05 and P2-06 exercise it |
| Immutable recipient and route selection | Each reply intent binds an immutable recipient, and each attempt keeps its original route | P2-09, P2-10, P2-11 and P2-12 exercise route changes and late callbacks |

### Delivery evidence and replay horizons

Delivery state changes are event records with provider-specific interpretation. An
older callback must not overwrite stronger later evidence without an explicit
provider rule. Webhook retries and outbox retries are at-least-once delivery
mechanisms. Accepted logical identities and external delivery guarantees remain
separate.

Before adding cleanup, define provider replay horizons and retained receipt and
delivery tombstones. Pruning display history cannot remove deduplication protection
while replay remains eligible. An expired identity follows a documented rejection
policy. Test delayed replay after history pruning.

### Separate commitment boundaries

Message acceptance, case commitment, provider delivery and user acknowledgement have
separate boundaries. A carrier account never grants end-user authority. Revisions
and exact confirmation govern any business operation through the case authority. An
uncertain send cannot be labelled failed merely to justify retry.

### Revision routing boundary (P2-I10)

The implemented router derives scope, logical case and operation identity from an
authenticated retained inbox read. It then validates a strict structured
investigation command.

- Current retained account access is distinct from the sender's current
  association. This slice supplies no association-revocation fence. The complete
  P2-12 commitment schedules below remain required.
- The standalone reference store owns only standalone case fixtures.
- Integrated mode calls the existing P1 authority through a fixed trusted local
  mapping, without copying current case state.

P1 revision CAS has no durable command receipt. A lost ACK remains unknown even
when fresh inspection later matches the proposal. Replay of the old expected
revision may conflict and cannot prove which original input won. This slice
introduces no automatic retry, rebase, timestamp arbitration, quote confirmation or
supplier action. These limits do not relax the V1 requirements below.

### Verified association lifecycle

A seeded-account association challenge binds:

- an opaque challenge identity;
- the intended account and provider sender;
- an expiration;
- a finite attempt limit.

Consume the challenge once through a protected atomic operation. Concurrent equal
use cannot create two associations. Reject expired, replayed or mismatched
challenges without case disclosure. Only the trusted adapter attaches
`AccountScope`.

Version associations so that revocation or phone-number reassignment cannot
transfer prior case ownership. New reads, command commitments and send admission
validate the current authorized association at their protected boundary. A familiar
number, browser session or LiveKit participant identity never substitutes for that
check.

P2-12 covers expired and reused challenges, concurrent consumption, revoked access
and reassigned numbers across intake, history, callbacks and routes. A newly
verified current association must still make useful progress.

### Acceptance sequence and business causality

Persist a server acceptance sequence with each committed logical input, scoped to
its tenant, verified account and conversation. Identical replay retains the original
sequence and receipt. Keep provider occurrence time and server receipt time as
separate observations.

The sequence orders accepted inputs within that namespace. It is neither a global
channel clock nor mutation authority. Case revision and exact confirmation remain
authoritative.

P2-05 and P2-06 exercise delayed, missing and skewed provider timestamps, a
controlled concurrent database revision race, stale linked confirmation and
ambiguous unlinked replies. Assert zero stale changes and successful current linked
progress at the actual case-authority transaction.

### Immutable recipient and authorized route selection

Bind each logical reply intent to an immutable tenant, account and conversation.
The delivery adapter may resolve a newly authorized channel or address for that same
recipient. It records the route and association version used by each attempt.

- Before a new send, revalidate routing permission and suppression state.
- Missing or revoked routes hold or reject safely. They cannot substitute another
  account.
- A fake-provider opt-out fixture must suppress a new send while leaving receipts
  and already observed delivery history intact.

Keep the logical outbound message identity stable. Give each local send invocation a
distinct attempt observation identity. When the provider supports idempotent sends,
preserve its idempotency key across retries of the same ambiguous send. Changing a
local attempt ID does not create a new provider operation. Retain the provider's
actual message or receipt identity when known.

An already sent or uncertain attempt remains bound to its original recipient,
address and provider operation. A route change cannot retarget that attempt or
justify a fresh send. Reconciliation or any separately authorized resend follows the
declared provider policy and retains the original uncertainty.

P2-09, P2-10, P2-11 and P2-12 hold delivery while a room closes or an association
changes. They verify a valid new route for the same recipient, reject a reassigned
recipient, and correlate late callbacks to the original attempt. Test both supported
stable provider keys and non-idempotent unknown outcomes.

A real carrier remains optional. Before claiming that a provider is supported, its
adapter qualification must document signature and replay verification, finite send
rate and retry limits, delivery evidence, and consent and opt-out behavior.

## Acceptance matrix

### Status

All seventeen rows remain planned and unregistered; see Implementation status.

### Test approach

All deterministic and process-failure cases use local services and fixtures. Media
assertions use an actual local LiveKit room and browser/audio fixtures. The shared
validation plan defines the offline, lab and live run profiles.

| ID | Scenario | Required observable result |
| --- | --- | --- |
| P2-01 | Replay identical scoped inbound event, including concurrent replay | One accepted logical message; stable original receipt |
| P2-02 | Reuse identity with altered semantic payload, retry with new receipt metadata, and send identical text under new IDs | Semantic change conflicts; metadata-only retry deduplicates; distinct messages both remain in history |
| P2-03 | Kill gateway after accepted acknowledgement and before agent dispatch | Restart recovers input; stable operation identity prevents duplicate business acceptance |
| P2-04 | Kill agent during processing, reconnect, and replay | Input and case remain recoverable; any repeated model processing is visible |
| P2-05 | Two channels submit competing commands for one revision | One revision transition wins; losing command receives conflict or clarification |
| P2-06 | Deliver an older confirmation after the request changes | Older intent cannot authorize current mutation; ambiguous unlinked reply asks clarification |
| P2-07 | Interrupt real browser audio output halfway through a response | Native interruption evidence is preserved; generated full response is not recorded as fully played |
| P2-08 | Disconnect client before playback evidence arrives | Playback completion remains unknown; no fabricated acknowledgement |
| P2-09 | Continue voice to browser chat to fake SMS after closing the room | Same verified case, current revision, relevant history, and work references load in a new interaction |
| P2-10 | Replay and reorder delivery callbacks | Attempt history and correlation remain correct; obsolete callback cannot silently regress state |
| P2-11 | Lose provider response after a simulated send without send idempotency | Ambiguous outcome is visible; policy does not claim guaranteed single physical delivery |
| P2-12 | Forge association, webhook signature, tenant, or another case ID | Request rejected without cross-account history or work disclosure |
| P2-13 | Burst input beyond configured processing capacity | Bounded queues and explicit rejection/defer behavior; every accepted item remains inspectable |
| P2-14 | Create many dormant conversations | No per-conversation active room or agent is required; active work remains bounded |
| P2-15 | Run native text and audio together through custom intake handling | Each committed input has one logical acceptance path; business effect dedupe remains intact |
| P2-16 | Start standalone example without Project 1 or Project 3 services | Case routing, fake delivery, history, and recovery contracts remain demonstrable |
| P2-17 | Hand package to a fresh coding agent through its documented harness | Agent can find contracts, run designated checks, distinguish planned from passing cases, and produce an inspectable change without hidden setup |

## Development checkpoints

| Step | Outcome | Gate |
| --- | --- | --- |
| Contract and standalone intake | Finalize event schemas and scoped identity; implement fake carrier intake, durable receipts, replay/conflict tests and crash-before-dispatch recovery | Not stated in this charter |
| Case continuity | Add verified synthetic association, case revisions, ambiguous confirmation handling and the standalone agent-dispatch adapter | Not stated in this charter |
| Local LiveKit integration | Add browser chat and voice, native interruption evidence, reconnect recovery and cross-language contract tests | Not stated in this charter |
| Delivery and bounded load | Add outbox attempts, delivery callbacks, ambiguous sends, overload behavior, dormant-thread measurements and a compact linked timeline | Not stated in this charter |
| Integrated release | Exercise Project 1 through its operation interface, record the cross-channel demo, review the public API and publish reproducible results | Installed npm-pack example once a real second consumer establishes the package boundary; repeat at release |

For the integrated release, when a real second consumer establishes the package
boundary, build an npm-pack artifact and install it outside the monorepo source
tree. Execute the minimal public-API example using only declared exports and
dependencies. Repeat this at release. Label optional real carrier and
model-provider checks separately.

## Release gates

| Gate | Required evidence | Notes |
| --- | --- | --- |
| Local-ready V1 | All P2 acceptance cases pass in their designated local lanes, and a clean setup runs the standalone and integrated examples | Cloud simulations, real SMS delivery and paid model credentials are not prerequisites |
| Portfolio-ready V1 | Selected real-model voice/text interactions against the same local application, with outcome, cost, API and failure-contract review | Real SMS remains optional; scripted speech fixtures alone do not establish model quality |
| Package contents | Minimal API example, failure contract, setup and recovery instructions, schema/version policy, playback limitations, contract-test results and latency/load evidence | Part of Local-ready V1, with passing type, lint, Python and cross-language contract checks |
| Installed-package check | An npm-pack artifact installed outside the monorepo source tree runs the minimal public-API example | Defined under Development checkpoints; repeat at release |
| Coding agent contract | `AGENTS.md`, `Design.md`, `README.md` and harness checks with stable P2 acceptance IDs | Missing or skipped implementations cannot count as passing |

### Local-ready V1

All P2 acceptance cases pass in their designated local lanes. A clean setup can run
the standalone and integrated examples with seeded synthetic data.

The demo shows:

- a real LiveKit voice interaction being interrupted, continued in browser text,
  and resumed through the fake SMS adapter after the room closes;
- duplicate intake and an obsolete confirmation handled without an incorrect case
  transition.

The package includes a minimal API example, failure contract, setup and recovery
instructions, schema/version policy, observed playback limitations, contract-test
results, and reproducible latency/load evidence. TypeScript type checking, linting,
relevant Python checks and cross-language contract tests pass.

Cloud simulations, real SMS delivery and paid model credentials are not
prerequisites for reproducing the required local release evidence.

### Portfolio-ready V1

In addition to the local gate, run selected real-model voice/text interactions
against the same local application. Check task outcomes, preserve configuration and
costs, review the public API and failure contract, and retain the required benchmark
and short success/failure demonstration. Real SMS remains optional. Scripted speech
fixtures alone do not establish model quality.

### Coding agent contract

When the package is introduced, it must include `AGENTS.md`, `Design.md` and
`README.md` at its documented entry point:

- `AGENTS.md` defines safe edit boundaries, required checks, fixture use and
  handling of credentials.
- `Design.md` records the event schema, acceptance boundary, case revisions,
  playback evidence and failure semantics.
- `README.md` provides setup, one minimal typed API example, standalone and
  integrated runs, and the implemented-versus-planned capability status.

The shared code-level harness must expose checks with stable P2 acceptance IDs,
machine-readable outcomes, evidence locations and bounded timeouts. Every ID appears
in its acceptance manifest with implementation status and test provenance. Missing
or skipped implementations cannot count as passing release evidence.

Contracts, fake provider fixtures, expected event histories and deterministic crash
points must be accessible without discovering private context from a chat. Changes
record the relevant IDs, decisions, verification results and AI assistance
accurately. A generated scaffold is not an unaided authorship claim.

## Deferred scope

| Area | Deferred item |
| --- | --- |
| Carrier adapters | Real carrier delivery, phone-number provisioning and public webhook tunnels, which are optional adapter validation after the fake carrier passes the contract |
| Other channels | WhatsApp, email, social messaging, group chat and additional carriers |
| Platform and transport | A general chat platform, custom WebRTC transport or custom audio synchronizer |
| Identity and data | Enterprise identity federation, account recovery and production customer data |
| Retention and memory | Raw audio/video archiving, unlimited transcript retention and automatic long-term memory extraction |
| Ordering and execution guarantees | Distributed global message ordering, exactly-once LLM execution, or guaranteed physical delivery when the carrier cannot provide the required contract |
| Dormant conversations | A permanent agent process or room for each dormant conversation |

## References

Use LiveKit's native session, text and interruption facilities.

| Document | Purpose |
| --- | --- |
| [Portfolio scope](../portfolio-scope.md) | Shared boundaries |
| [Validation plan](../validation-plan.md) | What counts as evidence |
| [P2 implementation plan](../implementation/p2-channel-continuity.md) | Task decomposition and per-task status |
| [Text and transcriptions](https://docs.livekit.io/agents/multimodality/text/) | Native `lk.chat` text input and synchronized output transcriptions |
| [Text streams](https://docs.livekit.io/transport/data/text-streams/) | Native text transport between connected participants, without long-term persistence |
