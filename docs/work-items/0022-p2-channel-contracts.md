# P2 versioned channel contract slice

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Implement P2-I01/I02 under PLAN-12: a strict bounded version-1 channel event
contract, real TypeScript text-event producer and TypeScript/Python decoders.
This contributes contract assertions to P2-02/P2-12, not complete acceptance.
Durable receipts, gateway, signature verification, association challenges,
PostgreSQL, media and P2-I03 through I06 remain planned.

| Criterion | Given / When | Safety | Useful progress |
| --- | --- | --- | --- |
| Contract parity | Shared valid/invalid JSON and a separately trusted principal | Reject duplicates, unknown fields/versions, malformed variants, scope mismatch and exceeded UTF-8 bounds | Both languages produce identical canonical bytes for valid events |
| Semantic identity | Repeat receivedAt/signature/retryCount, then change body/destination | Retry observations cannot alter identity; semantic changes produce distinct canonical bytes | Distinct event IDs remain distinct even with identical text |
| Trust | Caller supplies authenticated adapter configuration separately from payload | Parsing never verifies a signature, association or case permission | A valid scoped text producer yields a typed immutable event |

## Interfaces and ownership

P2 owns the TypeScript package and pure Python codec member. contracts/channel
owns synthetic cross-language fixtures. Root workspace/lock/check registration
is integrated by the primary agent. No imports of P1/P3 stores or services.
No parser or producer returns an accepted receipt. Receipt/history/reply port
types describe future implementations and grant no capability.

## Failure cases and validation

Use exact fields/discriminants, 32 KiB wire bound, 4 KiB text UTF-8 bound,
128-byte ASCII identifiers, UTC millisecond timestamps and safe integers.
Producer preflight additionally enforces 256 total visited nodes and 32 KiB
aggregate key/text UTF-8, including repeated visits to shared descendants; length
checks precede encoding. Reject duplicate JSON keys, lone surrogates, booleans as revisions and all
non-integer JSON numbers. Canonicalization sorts known ASCII keys, escapes all
non-ASCII UTF-16 code units and excludes receivedAt/signature/retryCount only.
Provider occurrence time and semantic account/case/conversation destinations
remain canonical. The trusted principal is configuration from a future verified
adapter; accepting its object is not authentication.

Required gates: G-FAST/G-CONTRACT and package build discovery. Run project
TypeScript typecheck/test/build, Python unittest and strict typing; root runs
shared fast/frontend/docs/format checks. No provider credentials, Docker or
network calls are required. There is no product runtime exporter; fixed safe
contract errors are tested and contain no raw payload. Future P2 runtime owns
logs/metrics and durable concurrency/process evidence.

## Results and handoff

P2-I01/I02 implementation and focused checks passed. The primary agent owns
final shared workspace/discovery/lock/documentation gates before this work item
can close. Full P2-A remains incomplete; no P2 acceptance runner is registered.

| Executed focused gate | Observed result |
| --- | --- |
| Python unittest project discovery | 14 tests passed, zero skips; all six valid and 38 invalid shared fixtures exercised |
| Python Ruff lint/format | Passed; three Python files formatted |
| Python strict typing | Passed for both codec source files |
| TypeScript package typecheck | Source and test TypeScript projects passed |
| TypeScript package test | Vitest passed 64 tests in one discovered test file |
| TypeScript package build | Production declarations and JavaScript emitted by tsc |

Commands ran from the repository root using the frozen workspace interpreter and
pinned pnpm toolchain:

```sh
.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v
.venv/bin/ruff check projects/channel-continuity/python/src projects/channel-continuity/tests
.venv/bin/ruff format --check projects/channel-continuity/python/src projects/channel-continuity/tests
.venv/bin/mypy --strict projects/channel-continuity/python/src
corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck
corepack pnpm --filter @livekit-ecosystem/channel-continuity test
corepack pnpm --filter @livekit-ecosystem/channel-continuity build
```

Independent automated review identified a JavaScript trailing-line-terminator
identifier mismatch. The codec now uses a true end assertion and shared LF/CR/
Unicode-line-separator fixtures. Producer review additionally led to global
traversal/text budgets, pre-encoding character bounds and array-hook rejection.
Tests preserve the normal producer path after these negative cases, exact wire/
text boundaries, canonical escape parity, metadata-only replay and immutable
outputs. Earlier lint/type issues were fixed; the final fail-fast focused run
passed. No provider credential, model endpoint, Docker service or network request
was used for these codec checks.

Next bounded slice is P2-I03's fake-carrier verification and versioned seeded
association lifecycle. Its authentication/challenge and protected access tests
must precede durable inbox acceptance. Contract fixtures alone do not establish
those controls, concurrent idempotency, actual carrier delivery or browser media.

### Shared validation and completion

The first P2/P3 slices passed the final root gates with independent automated
review. make check executed 1,132 Python tests: 1,079 root, 21 P1, 14 P2 and 18
P3, with zero skips and zero structural violations. Ruff passed; maintained
typing covered 95 sources and strict typing 35. make format-check passed for
231 Python files. make frontend-check passed console typing/build/326 tests and
P2 source/test typing/build/64 tests. All 95 documents passed and six project
Mermaid diagrams parsed; the invalid syntax fixture was rejected.

Root commands were also tested with temporary failing P2 test/type files: both
failed as required, and both files were removed before final validation. The
expanded Python discovery negative fixture covers P2 and P3 failure propagation.
Offline frozen installs included both dev-only members, without external version
upgrades. Both Dockerfiles rebuilt and eight default transport/auth/M1 checks
passed with the original M1 identity and ten audio frames. An owned nonroot,
network-disabled serving-image probe imported P1 and confirmed P2/P3 development
packages were absent. This smoke does not qualify either new product.

Evidence is retained under .local/validation/p2-p3-foundation/8c0eedd87dc746f5b56d02c3c01becc0.
The complete project acceptance catalogs still contain 17 planned/unregistered
rows each. No paid inference, new business database migration or remote CI ran.
Previous P1 release artifacts remain intact; these new checks are separate.

This completes P2-I01/I02 only. P2-A remains open for verified association,
durable inbox/idempotency and the standalone example before its phase exit.
