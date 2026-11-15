# P2 PostgreSQL association and durable inbox

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the P2 PostgreSQL association and durable inbox, their review corrections and the gates they passed |
| Audience | Engineers changing P2 storage, association, inbox acceptance or database roles; reviewers; coding agents |
| Scope | Tasks P2-I04 and P2-I05 and the P2-I06 intake portion; excludes dispatch, business actions, delivery and media |
| Owns | P2-I04 and P2-I05 change plan, observed verification and handoff |
| Related | [Verified intake](0024-p2-verified-durable-intake.md) · [P2 Design](../../projects/channel-continuity/Design.md) · [P2 charter](../projects/channel-continuity-scope.md) · [Standalone and HTTP](0027-p2-standalone-and-p3-http.md) |

## Behavior and scope

This work item implements tasks P2-I04 and P2-I05 and the intake portion of
P2-I06 on actual PostgreSQL. It builds on P2-I03's scoped fake-carrier
verification. Accepted input, the immutable receipt and the pending processing
intent commit together.

This slice implements no agent dispatch, business action, carrier delivery or
browser media. Phase P2-A still needs P2-I06's standalone developer example and
narrow adapter wiring. This work item does not close that phase or a complete P2
charter acceptance row.

| Criterion | Safety | Useful progress and evidence |
| --- | --- | --- |
| Signed association | Provider authentication alone grants no account/case authority; the signed LINK association message must contain the issued challenge secret | Seeded authenticated account plus verified sender activates one versioned binding |
| Protected identity | Original canonical event, receipt, sequence and operation key never change on replay | Concurrent equal requests and response-loss retry recover one original identity |
| Revision and revocation | Challenge consumes once under locks; revocation changes sender epoch and invalidates older challenges | A newly verified current binding progresses without inheriting prior account history |
| Capacity | Persisted guard serializes retained caps; no core identity deletion | Authorized replay and inspection remain available when new growth is rejected |
| Scope | Current verified association gates admission; account tokens gate reads | Cross-account receipt/cursor references reveal no records; current valid account progresses |

## Interfaces and ownership

### Database principals

P2 owns its isolated version-1 schema. The existing local `continuity_migrator`
owns data definition language (DDL) changes. `livekit_lab` receives narrow runtime
data manipulation language (DML) access without canonical UPDATE, DELETE, TRUNCATE
or schema privileges. Sharing this local credential does not establish P1/P2
database-principal isolation. A separately exposed deployment needs its own
principal before qualification. P1 schemas, credentials, volumes and media
defaults remain unchanged. No runtime performs DDL or silently repairs schema
drift.

### Exports and driver

The browser-safe codec stays the default export. Explicit server subpaths own
hash-based message authentication code (HMAC) handling and PostgreSQL. The
pure-JavaScript `pg` client and its type declarations are pinned at 8.23.1 after a
review of the maintained package and transaction documentation. One checked-out
client owns each transaction.

At most two pool connections and four admitted operations bound the pool waiting
queue. Server lock, statement and connect deadlines and shutdown are finite.
External calls never occur inside a protected transaction.

### Association and identity retention

- Sender heads retain monotonic epochs.
- Bindings are append-only except for a revocation time.
- Challenges retain consumed and attempt evidence.
- Original inbox and processing identities are retained indefinitely under finite
  caps.

A signed ordinary message cannot prove ownership of a new challenge: the verified
LINK body binds its UUID and random secret. Secrets are hashed at rest and
excluded from logs and reports. Account, conversation and case association comes
only from seeded trusted configuration.

### Admission and sequence

The schema admission row serializes counters and per-conversation sequence
allocation. Sequence allocation occurs under the same acceptance transaction. It
is a scoped acceptance order, never global chronology or business authority.
Actual database time is sampled after locks. Fresh batched catalog and role
validation rejects missing or changed schema, permissions, defaults, constraints
and indexes.

## Failure cases and validation

Required actual PostgreSQL cases include:

- concurrent replay and conflict;
- stable provider identity domains;
- malformed, expired, reused and racing challenges;
- revoke and reassign, and a stale challenge;
- cross-account reads;
- retained capacity;
- exact history paging;
- before-commit rollback and after-commit response loss;
- a fresh process replaying after real accepting-process termination.

The required lanes are:

| Lane | Required checks |
| --- | --- |
| P2 PostgreSQL | Every required case above, in an explicit non-default Node PostgreSQL lane; the runner owns random marked schemas, bounded children and cleanup |
| Migration and grants | Owner-only migration repeats validate rather than adopt or repair a foreign or drifted schema; runtime DDL, canonical mutation and destructive cleanup grants fail |
| Offline tests | Never silently connect or skip |
| Root and existing checks | Root fast, frontend, format and documentation checks and the appropriate existing PostgreSQL checks remain required |

Evidence rules for these lanes:

- Private credentials are supplied only through the existing local settings
  loader and child environment.
- Missing setup, zero tests, skips, timeout or cleanup failure remain non-passing.
- No provider key or real SMS account is needed.

## Results and handoff

### Outcome

P2-I03/I04/I05 passed their bounded implementation, actual PostgreSQL and final
shared gates. Signed carrier verification remains separate from seeded-account
association. The durable API commits the immutable message, receipt and pending
processing intent before acknowledgement. A retry under the original identity
returns the original receipt; it never silently creates another business action.

### Observed gates

| Executed gate | Observed result and limit |
| --- | --- |
| P2 offline TypeScript | 136 tests: 64 codec, 64 verifier and eight database/lifecycle; source/test strict typing, build and formatting passed |
| P2 actual PostgreSQL | All 12 named cases passed; zero failures/errors/skips, one actual accepting-child termination and complete owned cleanup |
| P1 actual PostgreSQL regression | All 263 existing tests passed with zero failures/errors/skips; existing P1 qualification artifacts retained |
| Shared Python/harness | 1,162 tests: 1,088 root, 21 P1, 14 P2 and 39 P3; zero skips/structural violations; Ruff passed, maintained typing covered 97 sources and strict typing 38 |
| Shared frontend | 504 tests: 326 console, 136 P2 and 42 P3; strict checks, Prettier and all builds passed |
| Documentation/format | All 99 documents passed, 236 Python files formatted, six Mermaid diagrams parsed and malformed syntax rejected; diagram check is syntax-only |
| Built npm consumers | Fresh outside-checkout consumer installed P2/P3 archives, passed strict TypeScript without @types/pg and ran codec/HMAC/server import/owned empty close/P3 decode; no database or provider call in this lane |
| Docker and transport | Default stack rebuilt with observability ready; all eight transport/authentication/M1 (confirmed-investigation intake) smoke checks passed, ten audio frames and original M1 identity preserved; no P2/P3 media qualification |

### Database case coverage

The real database cases cover:

- migration and runtime grants;
- signed possession;
- concurrent exact replay across two gateway instances, and changed-payload
  conflict;
- provider/tenant identity domains;
- capacity with reads and replay;
- challenge expiry, attempts and single use;
- revoke/reassign and private history;
- stable sequence/cursor paging;
- before-commit rollback and after-commit acknowledgement loss;
- a new process replay after the accepting child is actually killed.

Admission saturation proves that the fifth operation fails at a four-operation
cap and that valid work resumes after release.

### Independent review corrections

Independent automated review led to these tested corrections:

- Validate schema-metadata table shape through catalogs before reading any row. A
  substituted view containing a nontransactional sequence side effect is rejected
  by runtime and owner before its sequence is touched.
- Reject column collation, row-level security (RLS), rules/triggers and access
  control list (ACL), default, constraint or index drift. Existing-schema
  migration validates the immutable baseline rather than adopting or silently
  repairing changed state. Missing admission state also fails closed.
- Contain synchronous and asynchronous observer failures without unhandled
  rejection or changing accepted business state. Rejected association decisions
  commit their consumed attempts and emit rejection classifications.
- Bound owner/runtime cleanup, retain the primary safe failure, and drain owned
  admitted work. Separate public declarations from driver-specific internal types;
  the actual archive-consumer failure was preserved and corrected.
- Bind webhook message authentication codes (MACs) to the trusted provider scope.
  Retain original canonical bytes and the required processing intent on replay.
  Preserve active/current account authority across sender reassignment.

### Diagnostics and resource limits

Runtime logs expose fixed component, event, operation and code values. Counters
describe process-local acknowledgements, replay, rejection, dependency and
telemetry failures, plus active work. They are not authoritative database totals
or a deployed metrics exporter. Secret, proof, body and SQL parameters are
excluded. Public failures use fixed ChannelError codes. AcknowledgementUnknown
requires reconciliation with the same original identity and payload. Database
acceptedAt is an observation sampled within the transaction, not an exact commit
timestamp.

The two-connection pool, four-operation admission cap, indexed lookups and finite
lock/query/close budgets bound local resources. A persisted global admission guard
serializes growth and sequence accounting. This deliberate correctness trade-off
has not been throughput-qualified. The final 12-case run took about 2.09 seconds.
That is a correctness-run observation, not a latency percentile or capacity
result.

Core identity state is retained indefinitely under finite caps; no garbage
collector or replay-horizon deletion is implemented. The owner remains a trusted
migration principal. Sharing the existing local runtime database credential with
P1 is a local fixture limitation, not separate P1/P2 principal isolation.

### Commands, evidence and next tasks

Reproducible commands run from the repository root after frozen bootstrap,
restricted-role setup and the documented pinned Node/pnpm environment:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --report .local/validation/p2-postgres/fresh-run.json
make postgres-check POSTGRES_REPORT=.local/validation/postgres/fresh-run.json
make check
make frontend-check
make format-check
.venv/bin/python -m harness.documentation_check
.venv/bin/python local-setup/stack.py start --observability
.venv/bin/python local-setup/stack.py smoke
```

Report destinations must be fresh; choose unused names. Retained evidence:

| Evidence | Location |
| --- | --- |
| Actual P2 database reports | `first-20261110.json`, `reviewed-20261110.json` and `final-20261110.json` under `.local/validation/p2-postgres` |
| P1 regression report | `.local/validation/postgres/p2-p3-next-20261110.json` |
| Final logs, reviewed npm archives and consumer sources, the earlier archive failure, documentation/diagram results and the exact source index | `.local/validation/p2-p3-intake-contracts/0a88373e034e4ef8b2dca5fb8d4a7eb5` |

Earlier reports and P1 release artifacts remain intact.

AI assistance implemented and independently reviewed the bounded work. No paid
inference, real carrier, provider secret file, remote continuous integration (CI),
publication or production load qualification occurred. Both full P2/P3 acceptance
catalogs still contain 17 planned/unregistered rows.

Next, implement P2-I06's standalone fake-carrier example with public
case/scripted-agent/operation ports, then recoverable dispatch and the reply
outbox. P3-I03/I04 completed separately. Its next slice is P3-I05's authenticated
read-only HTTP handler/client, before coordinator durability and actual media.
