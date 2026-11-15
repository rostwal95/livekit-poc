# P2 verified provider boundary and durable intake

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the P2 synthetic-carrier verifier, its frozen webhook contract and its link to durable intake |
| Audience | Engineers changing P2 webhook verification, association or intake; reviewers; coding agents |
| Scope | Task P2-I03 and its handoff to P2-I04 and P2-I05; excludes the P2-I06 example, dispatch, delivery and media |
| Owns | P2-I03 change plan, synthetic webhook contract, observed verification and handoff |
| Related | [P2 channel contracts](0022-p2-channel-contracts.md) · [PostgreSQL inbox](0026-p2-postgres-inbox.md) · [P2 charter](../projects/channel-continuity-scope.md) · [P2 task plan](../implementation/p2-channel-continuity.md) |

## Behavior and scope

This work item continues Phase P2-A after the
[P2-I01/P2-I02 data contract](0022-p2-channel-contracts.md):

- Task P2-I03 authenticates the synthetic carrier independently of customer
  association.
- Tasks P2-I04 and P2-I05 add explicitly migrated PostgreSQL association, inbox,
  receipt and processing-intent state.
- Task P2-I06 proves the standalone input path.

This work item contributes assertions to acceptance IDs P2-01, P2-02, P2-03, P2-12
and P2-16 only where full scenarios exist. No real carrier account, external
provider key, model or P1/P3 service is required.

| Criterion | Given / When | Safety | Useful progress |
| --- | --- | --- | --- |
| Provider verification | Exact bounded carrier bytes and timestamp-bound message authentication code (MAC) arrive | Wrong key, tampering, malformed/expired signature and unknown scope fields fail uniformly | Genuine current signed input yields an immutable provider observation |
| Association | A trusted provider sender presents a bounded one-time challenge | Wrong/expired/replayed challenge and revoked/reassigned identity grant no case access | Current verified binding progresses under its original account and conversation |
| Durable acceptance | Authenticated input reaches the protected PostgreSQL transaction | No accepted acknowledgement before event/receipt/intent commit; conflicting reuse rejected | Concurrent retry returns original receipt and accepted order |
| Recovery | Accepted input or response acknowledgement is interrupted | Original provider identity and protection survive restart | A new standalone process replays or resumes original accepted input |

## Interfaces and ownership

P2 owns the TypeScript synthetic carrier verifier and the PostgreSQL adapters. The
security module authenticates only the configured integration/provider and the
sender claim in its signed body. Customer association and case access are
separate protected database decisions. Parsing a ChannelEvent or constructing a
principal is not authentication. The durable public intake accepts raw bytes and
headers and authenticates itself. A caller-supplied observation grants no account
authority.

### Frozen synthetic webhook contract

The external body has exactly these fields: `schemaVersion` (value 1), `eventId`,
`messageId`, `senderId`, `body` and `occurredAt`. Tenant, account, conversation
and case IDs cannot be supplied as carrier authority. Integration configuration
supplies the trusted ProviderScope and a 32–64-byte hash-based message
authentication code (HMAC) key, copied into private module state. No key appears
in serialized configuration, events, errors or logs. The authenticated observation
contains no customer account or route; association resolves them afterward.

The signature is lowercase HMAC-SHA256 over these exact UTF-8 parts, each followed
by a newline except the last:

1. the prefix `p2.fake_sms.v1`;
2. the trusted tenant ID;
3. the provider name;
4. the trusted provider-account ID;
5. the ten-digit timestamp in seconds;
6. the exact raw body bytes.

Identifier validation forbids newline delimiters. The signer requires the explicit
ProviderScope as its fourth argument; no unscoped signature fallback exists. This
pre-release contract decision prevents a key reused across two configured
accounts or tenants from making a webhook valid for both.

The headers are exactly timestamp and signature. The timestamp uses canonical
decimal epoch seconds and an inclusive 60-second past/future window. An old
captured webhook outside that window fails. Duplicate events inside the window
remain valid provider input and must deduplicate durably. The verifier maintains
no fake replay cache and makes no exactly-once claim.

The raw body is bounded to 32 KiB and snapshotted before MAC validation and strict
UTF-8 decoding:

- Compare fixed-size MACs using the platform constant-time helper.
- Check authenticity before parsing.
- The flat body decoder rejects duplicate keys, unknown fields, nested authority,
  unsupported schema and malformed JSON.
- Existing P2 producer validation supplies the same identifier, timestamp, Unicode
  and 4 KiB text rules. Its temporary validation context is neither a persisted
  conversation nor an association.

The synthetic signing helper is a local test/demo producer, not a real-carrier
adapter.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md).

| Gate | Required assertions | Mode and prerequisite |
| --- | --- | --- |
| G-READY/CONTRACT | Reviewed exact signature bytes, scope/association split, finite input/window bounds and fixed errors | Offline synthetic keys/fixtures only |
| G-FAST | Strict source/test TypeScript, discovered test files, build and root fast lanes | Frozen workspace dependencies |
| G-DURABLE | Actual migrations/restricted roles, protected challenge races, concurrent replay/conflict, restart and preserved receipts/order | Isolated PostgreSQL and owned processes; primary agent owns execution |
| G-OBS | WebhookRejected contains no raw body/signature/key; later runtime logs/metrics use fixed classifications | Actual error inspection; no placeholder metric producer |
| G-RELEASE | Ordinary useful progression, every required negative, finite cleanup and inspected retained evidence | Missing setup, skips, zero tests and timeout remain non-passing |

Verification tests use genuine HMAC signing and verification with synthetic
bytes. Cover:

- wrong key or integration;
- raw-body and signed-timestamp tampering;
- invalid MAC shape or case;
- expired and future timestamps, and inclusive window edges;
- malformed and duplicate JSON;
- forbidden account or case claims;
- oversized or malformed UTF-8 input;
- key ownership and output immutability;
- sanitized errors and valid progress after rejection.

Record duplicate-within-window behavior distinctly from database deduplication. No
credential file is read and no real provider endpoint is called.

## Results and handoff

### Completion

P2-I03 is completed together with the protected association/intake
implementation in the [PostgreSQL work item](0026-p2-postgres-inbox.md). This
verifier work item and P2-I04/I05 passed final shared gates and independent
automated review. P2-I06's standalone developer example, gateway dispatch,
delivery, channel transitions and media remain later tasks. No complete P2 charter
row is registered or qualified.

### Observed results

| Check | Observed result |
| --- | --- |
| Initial verifier checkpoint | Passed 128 tests: 64 existing codec and 64 provider-security tests |
| Final P2 discovery | Passed 136 tests after eight database/lifecycle unit tests were added |
| TypeScript source/test checks, build and formatting | Passed |
| Actual PostgreSQL lane | Passed all 12 named cases with zero skips |

The PostgreSQL cases include signed possession, challenge races/expiry/reuse,
revocation/reassignment, scoped replay/conflict and a real accepting-process
termination after commit.

### Verifier and association details

The verifier uses a fixed MAC vector independently computed with a second
implementation, and actual synthetic signer/consumer bytes, including valid MACs
on deliberately invalid bodies. A pre-release review bound the MAC to the trusted
tenant/provider/provider-account scope. Regression tests prove that reusing a key
across configured scopes cannot authorize cross-scope replay. In-window duplicate
authentication remains a provider observation; the durable inbox owns
deduplication.

Signed LINK proofs, the association messages that carry an issued challenge,
enter a dedicated one-time association path. Their secret is hashed at rest and
never enrolled as ordinary business text. Node security and storage remain
explicit server exports; the default event codec stays browser-safe.

The packed npm consumer passed strict typing without installing `@types/pg`. It
verified codec, signature and server imports outside the checkout. This narrow
artifact smoke does not close the complete standalone package/release gate.

### Commands and evidence

Run from the root with the pinned toolchain and the prepared restricted local
database:

```sh
corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck
corepack pnpm --filter @livekit-ecosystem/channel-continuity test
make p2-postgres-check
make check
make frontend-check
```

The final shared results and retained source/evidence inventory are recorded in
the [PostgreSQL handoff](0026-p2-postgres-inbox.md). No provider credential file,
real SMS endpoint, paid model, remote continuous integration (CI) or publication
was used. AI assistance implemented and independently reviewed these boundaries.
Human API sign-off and production workload qualification are not claimed.
