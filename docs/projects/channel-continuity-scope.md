# Channel Continuity Kit scope

Status: Active
Last reviewed: 13 November 2026

## Overview

Build a TypeScript SDK and gateway that preserve a synthetic travel-support case
across LiveKit voice, browser text, and asynchronous SMS interactions. A new
interaction can load the current case and relevant communication history without
keeping a room or an agent process alive for every dormant conversation.

Continuity accounts for interrupted output: generated text, reported playback,
provider delivery and explicit user acknowledgement remain separate observations.
The [portfolio scope](../portfolio-scope.md) defines shared boundaries, and the
[validation plan](../validation-plan.md) defines evidence. This charter is
authoritative for P2 behavior and acceptance IDs.

## Implementation status

The first P2-I01/I02 slice implements versioned TypeScript/Python event contracts
and producer/decoder parity fixtures. I03/I04/I05 add signed fake-SMS verification,
seeded association and PostgreSQL inbox/receipts/pending processing intent. I06 adds
a standalone public-export fake-carrier example with separate read-only preview;
its operation observation explicitly remains not_executed only while input is
pending. I07 adds an explicit owner v1-to-v2 upgrade and bounded persisted
investigation dispatch/lookup-only reconciliation. Original prepared input and
operation identity survive takeover; possible external acceptance remains uncertain
until a matching cooperating-port receipt is observed. A nonpending input cannot
reuse the old not_executed preview. I08 adds an actual bounded loopback gateway
with raw authenticated intake, persisted eligible selection and recovery after
accepted acknowledgement/process loss. It has no in-memory acceptance queue.
I09 adds an explicit trusted agent-process adapter and worker protocol. The live
gateway can retain a committed message after independent scripted-worker death,
observe claim expiry and reprocess the original immutable input/case/operation
context. Attempts are visible while cooperating operation acceptance stays one
logical investigation. Selected phase gates passed for this bounded I09 failure path;
I10 adds explicit RevisionRouter and CaseAuthorityPort contracts over strict
structured investigation commands read from authenticated retained inbox input.
Standalone reference PostgreSQL authority and integrated P1 loopback bridge use
one selected authority each. Current case CAS, stale conflict, clarification and
unknown acknowledgement stay distinct. The selected 22-case equivalent-authority
gate passed; final phase/task qualification remains recorded in the work item.
Later selected tasks through I20 add linked exact confirmation, immutable outbound
replies, correlated callbacks, explicit uncertain-send recovery, native text/voice,
scoped playback/context, bounded workload studies and the read-only operations UI.
Their separate handoffs retain exact qualification boundaries. No parser or
canonical event grants account authority or proves persisted acceptance. All
seventeen complete acceptance rows remain planned/unregistered until every required
assertion passes. The [0040 handoff](../work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records the selected operations checkpoint; subsequent standalone and result-return
qualification is summarized below. The earlier
[routing](../work-items/0031-revision-routing-and-delegation-acceptance.md) and
[contract](../work-items/0022-p2-channel-contracts.md) work items retain their original scope.

### Current selected standalone and result-return checkpoint

P2-I20 read-only operations/telemetry retains its qualified
[0040 handoff](../work-items/0040-operations-ui-and-fixed-policy-evidence.md).
The completed [0041 handoff](../work-items/0041-standalone-channel-and-durable-policy.md)
qualified P2-I21's twenty installed standalone assertions and six separate
public-P1 assertions. P3-I18B subsequently passed selected source/installed native
RTC text qualification in [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md);
that separate application does not establish joined P2 voice/SMS routing.

The completed [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
qualified the P2 v8 receiver/current-channel data-read seam and P3's v2 result
delivery: sixteen storage and four return source assertions passed. Its separate
twenty-five-stage offline package lane qualifies isolated consumers, not an
installed repetition of those twenty actual source assertions. A current native
grant data read does not establish RTC media or provider inference.

The [0044 work item](../work-items/0044-origin-bound-channel-policy.md)
implements the original P2-input binding, schema3 policy facades, narrow operation
client and local application HTTP boundary. Focused unit/socket checks and isolated
package/fake-port qualification passed; the fourteen-assertion actual source
gate passed with complete cleanup. P2-I22 release, joined native voice/text/SMS handoff, broader
restart/discovery, applicable provider runs and the final video retain their later
gates. All seventeen complete P2 acceptance rows remain planned/unregistered;
the catalog remains fifty-five definitions and twenty-four registered runners.

## Ownership and dependencies

| Component | Owns |
| --- | --- |
| TypeScript channel package | Versioned events, scoped identities, message acceptance, delivery semantics, case routing, adapter interfaces |
| TypeScript gateway | Provider verification, normalization, persisted inbox and outbox, retries, synthetic account association |
| Python LiveKit adapter | Loading scoped case context, routing accepted input into the agent, recording native conversation and interruption events |
| Browser client | Native LiveKit audio and text interaction, reconnect handling, clearly labelled client playback observations |
| Case store | Authoritative case revision and confirmed facts, separate from room identity and generated summaries |
| Project 1 integration | Durable business execution and supplier effects through a narrow operation port |

This project does not own supplier execution, workflow recovery, or specialist
scheduling. It can run independently using a small local case store, scripted
agent adapter, and fake operation port. Project 1 is an integration adapter, not
a required deployment for the standalone example. Project 3 is not a dependency.

Use LiveKit's existing `lk.chat` text input and hybrid/text-only session support.
Its synchronized output transcriptions already stop and truncate on interruption;
consume that behavior rather than implementing a speech synchronizer. Evaluate
the official Agents UI components when introducing the product conversation
client; retain application-specific durable receipts and history behind the
continuity contract. The existing diagnostic console need not be rewritten merely
to add a framework.
[Text and transcriptions](https://docs.livekit.io/agents/multimodality/text/)

Native text streams transport data between connected participants and do not
provide long-term message persistence. This SDK supplies the application history
and acceptance protocol needed by the reference case.
[Text streams](https://docs.livekit.io/transport/data/text-streams/)

## Required V1 behavior

1. Accept committed user text from browser chat and the fake SMS carrier through
   one typed intake contract. Interim speech transcripts are observations, not
   confirmed business commands.
2. Acknowledge an input as accepted only after its canonical payload, stable
   identity, destination, and processing intent are committed. Browser inputs show
   pending, accepted, and failed states; sending a realtime stream alone is not
   an application acceptance acknowledgement.
3. Recover accepted pending input after gateway or agent restart. Processing may
   run again; stable operation identities prevent repeated acceptance of the same
   logical business work. Do not promise exactly one LLM invocation.
4. Deduplicate by tenant, provider, provider account, and provider event identity.
   Identical replay returns the original receipt; changed content under the same
   identity produces a conflict. Two distinct messages containing "yes" remain
   distinct inputs. Canonicalization includes the semantic event payload and
   stable destination, but excludes local receipt times, retry counters, transport
   signatures, and other delivery-attempt metadata. Preserve such metadata as
   observations so an ordinary provider retry cannot create a false conflict.
5. Preserve conversation, case, message, response, and room identifiers. A case
   can span multiple rooms; an archived room is not the case's state store.
6. Use a transaction and expected case revision when changing confirmed case
   intent. Resolve competing voice and text commands explicitly. Arrival time or
   a carrier timestamp does not establish a universal order across channels.
7. Associate commands with the case revision and prompt or response they answer
   when that information exists. A delayed confirmation for an older revision
   cannot silently confirm the latest request. An ambiguous SMS "yes" causes
   clarification; do not invent a revision association from the current room.
8. Provide a minimal, verified association flow for seeded synthetic accounts.
   Unassociated senders cannot access a case. Provider webhook verification and
   user account association are separate checks. Test tenant separation in all
   reads, writes, callbacks, and routing paths.
9. Persist outgoing notification intent with a stable message identity. Correlate
   callbacks, preserve attempt history, bound retries, and represent ambiguous
   delivery. A provider that lacks idempotent sends cannot support a guarantee of
   one physical SMS delivery after an uncertain send outcome.
10. Record output evidence with its source and uncertainty. Distinguish generated
    response, SDK-reported progress/interruption, client-reported playback,
    carrier delivery/read reports, and explicit user acknowledgement. Missing
    evidence remains unknown. None of these events alone proves comprehension or
    grants permission for a booking mutation.
11. On reconnect or channel change, rehydrate authoritative case facts, relevant
    accepted messages, pending work references, and communication evidence. A
    generated summary cannot override the case revision or supplier outcome.
12. Ship one independently runnable fake-carrier example and one integrated
    browser example using an actual local LiveKit server. The required path uses
    no LiveKit Cloud feature or real carrier account.

For browser text that can change case intent, custom input handling must persist
acceptance before dispatching to the agent. Do not also let a default automatic
reply path consume that same input and produce a second logical action. For voice,
record committed utterances and native output evidence; require the application's
explicit confirmation contract before invoking business operations.

## Public contracts

The following is the intended custom SDK shape. These names are illustrative
until the contract checkpoint; they are not existing LiveKit SDK methods.

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

`TrustedPrincipal`, `Receipt`, `ReplyIntent`, `MessageRecord`, and `HistoryPage`
are exported data contracts at the first codec checkpoint. The TrustedPrincipal
value must come from a separately authenticated adapter; constructing or parsing
one does not establish authentication. Scope inside an event is
validated against the trusted principal or verified provider adapter; a caller
cannot grant itself access by supplying a tenant ID. History is bounded and
paginated. Raw audio/video is carried by LiveKit media tracks, not inserted into
this text-event envelope. Event variants have their own payload schemas and
retain ordering and provenance information without forcing every modality into a
text message.

`ProviderScope` identifies a carrier/integration account and scopes provider-event
deduplication. It does not identify or authorize the end user. `AccountScope`
identifies the business account after verified association; only the trusted
association service may attach it to inbound provider events. An unassociated
event cannot read a case merely because its provider account is recognized.

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

Delivery state changes are event records with provider-specific interpretation.
An older callback must not overwrite stronger later evidence without an explicit
provider rule. Webhook retries and outbox retries are at-least-once delivery
mechanisms; accepted logical identities and external delivery guarantees remain
separate. Before adding cleanup, define provider replay horizons and retained
receipt/delivery tombstones. Pruning display history cannot remove deduplication
protection while replay remains eligible; an expired identity follows a documented
rejection policy. Test delayed replay after history pruning.

Message acceptance, case commitment, provider delivery and user acknowledgement
have separate boundaries. A carrier account never grants end-user authority;
revisions and exact confirmation govern any business operation through the case
authority. An uncertain send cannot be labelled failed merely to justify retry.

### Current I10 routing boundary

The implemented router derives scope, logical case and operation identity from an
authenticated retained inbox read, then validates a strict structured investigation
command. Current retained account access is distinct from the sender's current
association; this slice supplies no association-revocation fence. The complete
P2-12 commitment schedules below remain required. The standalone reference store
owns only standalone case fixtures; integrated mode calls the existing P1 authority
through a fixed trusted local mapping, without copying current case state.

P1 revision CAS has no durable command receipt. A lost ACK remains unknown even
when fresh inspection later matches the proposal; replay of the old expected
revision may conflict and cannot prove which original input won. No automatic
retry, rebase, timestamp arbitration, quote confirmation or supplier action is
introduced. These limits do not relax V1 requirements below.

### Verified association lifecycle

A seeded-account association challenge binds an opaque challenge identity, the
intended account and provider sender, an expiration and a finite attempt limit.
Consume it once through a protected atomic operation; concurrent equal use cannot
create two associations. Reject expired, replayed or mismatched challenges without
case disclosure. Only the trusted adapter attaches AccountScope.

Version associations so revocation or phone-number reassignment cannot transfer
prior case ownership. New reads, command commitments and send admission validate
the current authorized association at their protected boundary. A familiar number,
browser session or LiveKit participant identity never substitutes for that check.
P2-12 covers expired/reused challenges, concurrent consumption, revoked access and
reassigned numbers across intake, history, callbacks and routes; a newly verified
current association must still make useful progress.

### Acceptance sequence and business causality

Persist a server acceptance sequence with each committed logical input, scoped to
its tenant, verified account and conversation. Identical replay retains the original
sequence and receipt. Keep provider occurrence time and server receipt time as
separate observations. The sequence orders accepted inputs within that namespace;
it is neither a global channel clock nor mutation authority. Case revision and
exact confirmation remain authoritative. P2-05/P2-06 exercise delayed, missing and
skewed provider timestamps, a controlled concurrent database revision race, stale
linked confirmation and ambiguous unlinked replies. Assert zero stale changes and
successful current linked progress at the actual case-authority transaction.

### Immutable recipient and authorized route selection

Bind each logical reply intent to an immutable tenant, account and conversation.
The delivery adapter may resolve a newly authorized channel/address for that same
recipient while recording the route and association version used by each attempt.
Before a new send, revalidate routing permission and suppression state. Missing or
revoked routes hold or reject safely; they cannot substitute another account.
A fake-provider opt-out fixture must suppress a new send while leaving receipts
and already observed delivery history intact.

Keep the logical outbound message identity stable. Give each local send invocation
a distinct attempt observation identity. When the provider supports idempotent
sends, preserve its idempotency key across retries of the same ambiguous send;
changing a local attempt ID does not create a new provider operation. Retain the
provider's actual message/receipt identity when known. An already sent or uncertain
attempt remains bound to its original recipient, address and provider operation:
a route change cannot retarget that attempt or justify a fresh send. Reconciliation
or any separately authorized resend follows the declared provider policy and
retains the original uncertainty.

P2-09/P2-10/P2-11/P2-12 hold delivery while a room closes or an association changes,
verify a valid new route for the same recipient, reject a reassigned recipient,
and correlate late callbacks to the original attempt. Test both supported stable
provider keys and non-idempotent unknown outcomes. A real carrier remains optional;
its adapter qualification must document signature/replay verification, finite send
rate/retry limits, delivery evidence and consent/opt-out behavior before claiming
that provider is supported.

## Acceptance matrix

All deterministic and process-failure cases use local services and fixtures.
Media assertions use an actual local LiveKit room and browser/audio fixtures.
The shared validation plan defines the offline, lab, and live run profiles.

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

1. **Contract and standalone intake.** Finalize event schemas and scoped identity,
   implement fake carrier intake, durable receipts, replay/conflict tests, and
   crash-before-dispatch recovery.
2. **Case continuity.** Add verified synthetic association, case revisions,
   ambiguous confirmation handling, and the standalone agent-dispatch adapter.
3. **Local LiveKit integration.** Add browser chat and voice, native interruption
   evidence, reconnect recovery, and cross-language contract tests.
4. **Delivery and bounded load.** Add outbox attempts, delivery callbacks,
   ambiguous sends, overload behavior, dormant-thread measurements, and a compact
   linked timeline.
5. **Integrated release.** Exercise Project 1 through its operation interface,
   record the cross-channel demo, review the public API, and publish reproducible
   results. When a real second consumer establishes the package boundary, build an
npm-pack artifact, install it outside the monorepo source tree and execute the
minimal public-API example using only declared exports/dependencies. Repeat at
release. Optional real carrier and model-provider checks are labelled apart.

## Release gates

### Local-ready V1

All P2 acceptance cases pass in their designated local lanes. A clean setup can
run the standalone and integrated examples with seeded synthetic data. The demo
shows a real LiveKit voice interaction being interrupted, continued in browser
text, and resumed through the fake SMS adapter after the room closes. It also
shows duplicate intake and an obsolete confirmation handled without an incorrect
case transition.

The package includes a minimal API example, failure contract, setup and recovery
instructions, schema/version policy, observed playback limitations, contract-test
results, and reproducible latency/load evidence. TypeScript type checking,
linting, relevant Python checks, and cross-language contract tests pass. Cloud
simulations, real SMS delivery, and paid model credentials are not prerequisites
for reproducing the required local release evidence.

### Portfolio-ready V1

In addition to the local gate, run selected real-model voice/text interactions
against the same local application. Check task outcomes, preserve configuration
and costs, review the public API and failure contract, and retain the required
benchmark and short success/failure demonstration. Real SMS remains optional;
scripted speech fixtures alone do not establish model quality.

### Coding agent contract

When the package is introduced, it must include `AGENTS.md`, `Design.md`, and
`README.md` at its documented entry point. `AGENTS.md` defines safe edit boundaries,
required checks, fixture use, and handling of credentials. `Design.md` records the
event schema, acceptance boundary, case revisions, playback evidence, and failure
semantics. `README.md` provides setup, one minimal typed API example, standalone
and integrated runs, and the implemented-versus-planned capability status.

The shared code-level harness must expose checks with stable P2 acceptance IDs,
machine-readable outcomes, evidence locations, and bounded timeouts. Every ID
appears in its acceptance manifest with implementation status and test provenance.
Missing or skipped implementations cannot count as passing release evidence.
Contracts, fake provider fixtures, expected event histories, and deterministic
crash points must be accessible without discovering private context from a chat.
Changes record the relevant IDs, decisions, verification results, and AI
assistance accurately; a generated scaffold is not an unaided authorship claim.

## Deferred scope

- Real carrier delivery, phone-number provisioning, and public webhook tunnels
  are optional adapter validation after the fake carrier passes the contract.
- WhatsApp, email, social messaging, group chat, and additional carriers.
- A general chat platform, custom WebRTC transport, or custom audio synchronizer.
- Enterprise identity federation, account recovery, and production customer data.
- Raw audio/video archiving, unlimited transcript retention, and automatic
  long-term memory extraction.
- Distributed global message ordering, exactly-once LLM execution, or guaranteed
  physical delivery when the carrier cannot provide the required contract.
- A permanent agent process or room for each dormant conversation.

## References

Use LiveKit's native session, text and interruption facilities. See
[text and transcriptions](https://docs.livekit.io/agents/multimodality/text/) and
[text streams](https://docs.livekit.io/transport/data/text-streams/).
