# P2 verified provider boundary and durable intake

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Continue Phase P2-A after the [I01/I02 data contract](0022-p2-channel-contracts.md).
P2-I03 authenticates the synthetic carrier independently of customer association.
P2-I04/I05 add explicitly migrated PostgreSQL association, inbox, receipt and
processing-intent state; P2-I06 proves the standalone input path. This work item
contributes P2-01/P2-02/P2-03/P2-12/P2-16 assertions only where full scenarios exist.
No real carrier account, external provider key, model or P1/P3 service is required.

| Criterion | Given / When | Safety | Useful progress |
| --- | --- | --- | --- |
| Provider verification | Exact bounded carrier bytes and timestamp-bound MAC arrive | Wrong key, tampering, malformed/expired signature and unknown scope fields fail uniformly | Genuine current signed input yields an immutable provider observation |
| Association | A trusted provider sender presents a bounded one-time challenge | Wrong/expired/replayed challenge and revoked/reassigned identity grant no case access | Current verified binding progresses under its original account and conversation |
| Durable acceptance | Authenticated input reaches the protected PostgreSQL transaction | No accepted acknowledgement before event/receipt/intent commit; conflicting reuse rejected | Concurrent retry returns original receipt and accepted order |
| Recovery | Accepted input or response acknowledgement is interrupted | Original provider identity and protection survive restart | A new standalone process replays or resumes original accepted input |

## Interfaces and ownership

P2 owns the TypeScript synthetic carrier verifier and PostgreSQL adapters. The
security module authenticates only the configured integration/provider and sender
claim in its signed body. Customer association and case access are separate
protected database decisions. Parsing a ChannelEvent or constructing a principal
is not authentication. The durable public intake accepts raw bytes/headers and
authenticates itself; a caller-supplied observation grants no account authority.

### Frozen synthetic webhook contract

The external body has exactly schemaVersion 1, eventId, messageId, senderId, body
and occurredAt. Tenant, account, conversation and case IDs cannot be supplied as
carrier authority. Integration configuration supplies trusted ProviderScope and a
32–64-byte HMAC key, copied into private module state. No key appears in serialized
configuration, events, errors or logs. The authenticated observation contains no
customer account or route; association resolves them afterward.

The signature is lowercase HMAC-SHA256 over the exact UTF-8 prefix
p2.fake_sms.v1 followed by newline, trusted tenant ID, newline, provider name,
newline, trusted provider-account ID, newline, ten-digit timestamp seconds, newline
and exact raw body bytes. Identifier validation forbids newline delimiters. The
signer requires the explicit ProviderScope as its fourth argument; no unscoped
signature fallback exists. This pre-release contract decision prevents a reused
key across two configured accounts/tenants from making a webhook valid for both. Headers are exactly timestamp and signature. The timestamp uses
canonical decimal epoch seconds and an inclusive 60-second past/future window.
An old captured webhook outside that window fails. Duplicate events inside it
remain valid provider input and must deduplicate durably; the verifier maintains
no fake replay cache or exactly-once claim.

Raw body is bounded to 32 KiB and snapshotted before MAC validation and strict
UTF-8 decoding. Compare fixed-size MACs using the platform constant-time helper.
Check authenticity before parsing. The flat body decoder rejects duplicate keys,
unknown fields, nested authority, unsupported schema and malformed JSON. Existing
P2 producer validation supplies the same identifier, timestamp, Unicode and 4 KiB
text rules; its temporary validation context is neither a persisted conversation
nor an association. The synthetic signing helper is a local test/demo producer,
not a real-carrier adapter.

## Failure cases and validation

| Gate | Required assertions | Mode and prerequisite |
| --- | --- | --- |
| G-READY/CONTRACT | Reviewed exact signature bytes, scope/association split, finite input/window bounds and fixed errors | Offline synthetic keys/fixtures only |
| G-FAST | Strict source/test TypeScript, discovered test files, build and root fast lanes | Frozen workspace dependencies |
| G-DURABLE | Actual migrations/restricted roles, protected challenge races, concurrent replay/conflict, restart and preserved receipts/order | Isolated PostgreSQL and owned processes; primary agent owns execution |
| G-OBS | WebhookRejected contains no raw body/signature/key; later runtime logs/metrics use fixed classifications | Actual error inspection; no placeholder metric producer |
| G-RELEASE | Ordinary useful progression, every required negative, finite cleanup and inspected retained evidence | Missing setup, skips, zero tests and timeout remain non-passing |

Verification tests use genuine HMAC signing/verification with synthetic bytes.
Cover wrong key/integration, raw-body and signed-timestamp tamper, invalid MAC
shape/case, expired and future timestamps, inclusive window edges, malformed and
duplicate JSON, forbidden account/case claims, oversized/malformed UTF-8 input,
key ownership, output immutability, sanitized errors and valid progress after
rejection. Record duplicate-within-window behavior distinctly from DB dedupe.
No credential file is read and no real provider endpoint is called.

## Results and handoff

P2-I03 is completed together with the protected association/intake implementation
in the [PostgreSQL work item](0026-p2-postgres-inbox.md). This verifier work item
and I04/I05 passed final shared gates and independent automated review. I06's
standalone developer example, gateway dispatch, delivery, channel transitions and
media remain later tasks. No complete P2 charter row is registered or qualified.

The initial verifier checkpoint passed 128 tests: 64 existing codec and 64
provider-security tests. Final P2 discovery passed 136 tests after eight database/
lifecycle unit tests were added. TypeScript source/test checks, build and formatting
passed. The actual PostgreSQL lane passed all 12 named cases with zero skips,
including signed possession, challenge races/expiry/reuse, revocation/reassignment,
scoped replay/conflict and a real accepting-process termination after commit.

The verifier uses a fixed MAC vector independently computed with a second
implementation and actual synthetic signer/consumer bytes, including valid MACs
on deliberately invalid bodies. A pre-release review bound the MAC to trusted
tenant/provider/provider-account scope. Regression tests prove that reusing a key
across configured scopes cannot authorize cross-scope replay. In-window duplicate
authentication remains a provider observation; the durable inbox owns deduplication.

Signed LINK proofs enter a dedicated one-time association path. Their secret is
hashed at rest and never enrolled as ordinary business text. Node security/storage
remain explicit server exports; the default event codec stays browser-safe.
The packed npm consumer passed strict typing without installing @types/pg and
verified codec/signature/server imports outside the checkout. This narrow artifact
smoke does not close the complete standalone package/release gate.

Run from the root with the pinned toolchain and prepared restricted local database:

```sh
corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck
corepack pnpm --filter @livekit-ecosystem/channel-continuity test
make p2-postgres-check
make check
make frontend-check
```

The final shared results and retained source/evidence inventory are recorded in
the [PostgreSQL handoff](0026-p2-postgres-inbox.md). No provider credential file,
real SMS endpoint, paid model, remote CI or publication was used. AI assistance
implemented and independently reviewed these boundaries; human API sign-off and
production workload qualification are not claimed.
