# P2 versioned channel contract slice

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the strict version-1 P2 channel event contract, its producer and decoders, and their gates |
| Audience | Engineers changing P2 channel contracts, codecs or shared fixtures; reviewers; coding agents |
| Scope | Tasks P2-I01 and P2-I02 under PLAN-12; excludes receipts, gateway, signatures, PostgreSQL and media |
| Owns | P2-I01 and P2-I02 change plan, observed verification and handoff |
| Related | [P2 charter](../projects/channel-continuity-scope.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [Contracts guide](../../contracts/README.md) · [P3 native baseline](0023-p3-native-baseline.md) · [Verified intake](0024-p2-verified-durable-intake.md) |

## Behavior and scope

This work item implements tasks P2-I01 and P2-I02 under work package PLAN-12 of
the [build plan](../build-plan.md). It delivers:

- a strict, bounded version-1 channel event contract;
- a real TypeScript text-event producer;
- TypeScript and Python decoders.

The slice contributes contract assertions to acceptance IDs P2-02 and P2-12, not
complete acceptance. Durable receipts, the gateway, signature verification,
association challenges, PostgreSQL, media and tasks P2-I03 through P2-I06 remain
planned.

| Criterion | Given / When | Safety | Useful progress |
| --- | --- | --- | --- |
| Contract parity | Shared valid/invalid JSON and a separately trusted principal | Reject duplicates, unknown fields/versions, malformed variants, scope mismatch and exceeded UTF-8 bounds | Both languages produce identical canonical bytes for valid events |
| Semantic identity | Repeat receivedAt/signature/retryCount, then change body/destination | Retry observations cannot alter identity; semantic changes produce distinct canonical bytes | Distinct event IDs remain distinct even with identical text |
| Trust | Caller supplies authenticated adapter configuration separately from payload | Parsing never verifies a signature, association or case permission | A valid scoped text producer yields a typed immutable event |

## Interfaces and ownership

| Owner | Responsibility |
| --- | --- |
| P2 | The TypeScript package and the pure Python codec member |
| `contracts/channel` | Synthetic cross-language fixtures |
| Primary agent | Root workspace, lock and check registration integration |

The slice imports no P1 or P3 stores or services. No parser or producer returns an
accepted receipt. Receipt, history and reply port types describe future
implementations and grant no capability.

## Failure cases and validation

### Contract bounds

| Limit | Value |
| --- | --- |
| Fields and discriminants | Exact |
| Wire | 32 KiB |
| Text | 4 KiB UTF-8 |
| Identifiers | 128-byte ASCII |
| Timestamps | UTC milliseconds |
| Integers | Safe integers |
| Producer preflight nodes | Additionally enforces 256 total visited nodes |
| Producer preflight text | Additionally enforces 32 KiB of aggregate key and text UTF-8 |

The preflight count includes repeated visits to shared descendants. Length checks
precede encoding. Reject duplicate JSON keys, lone surrogates, booleans as
revisions and all non-integer JSON numbers.

Canonicalization sorts known ASCII keys and escapes all non-ASCII UTF-16 code
units. It excludes only `receivedAt`, `signature` and `retryCount`. Provider
occurrence time and the semantic account, case and conversation destinations
remain canonical. The trusted principal is configuration from a future verified
adapter. Accepting its object is not authentication.

### Required gates

The required gates are G-FAST and G-CONTRACT from the
[validation plan](../validation-plan.md), plus package build discovery. Run these
lanes:

| Lane | Required checks |
| --- | --- |
| Project | TypeScript typecheck, test and build; Python unittest and strict typing |
| Root | Shared fast, frontend, documentation and format checks |

No provider credentials, Docker or network calls are required.

There is no product runtime exporter. Fixed safe contract errors are tested and
contain no raw payload. The future P2 runtime owns logs, metrics and durable
concurrency/process evidence.

## Results and handoff

P2-I01/I02 implementation and focused checks passed. The final shared workspace,
discovery, lock and documentation results are recorded under
[Shared validation and completion](#shared-validation-and-completion). At this
checkpoint, the wider Phase P2-A remained incomplete and no P2 acceptance runner
was registered.

### Focused gates

| Executed focused gate | Observed result |
| --- | --- |
| Python unittest project discovery | 14 tests passed, zero skips; all six valid and 38 invalid shared fixtures exercised |
| Python Ruff lint/format | Passed; three Python files formatted |
| Python strict typing | Passed for both codec source files |
| TypeScript package typecheck | Source and test TypeScript projects passed |
| TypeScript package test | Vitest passed 64 tests in one discovered test file |
| TypeScript package build | Production declarations and JavaScript emitted by tsc (the TypeScript compiler) |

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

### Review findings

Independent automated review identified a JavaScript identifier mismatch caused
by a trailing line terminator. The codec now uses a true end assertion and shared
fixtures for line feed (LF), carriage return (CR) and the Unicode line separator.
Producer review additionally led to:

- global traversal and text budgets;
- character bounds checked before encoding;
- array-hook rejection.

Tests preserve the normal producer path after these negative cases. They also
cover exact wire and text boundaries, canonical escape parity, metadata-only
replay and immutable outputs. Earlier lint and type issues were fixed, and the
final fail-fast focused run passed. No provider credential, model endpoint, Docker
service or network request was used for these codec checks.

### Shared validation and completion

The [P3 native baseline work item](0023-p3-native-baseline.md) records the same
shared validation. The first P2/P3 slices passed the final root gates with
independent automated review:

| Check | Observed result |
| --- | --- |
| `make check` | Executed 1,132 Python tests (1,079 root, 21 P1, 14 P2 and 18 P3), with zero skips and zero structural violations |
| Ruff and typing | Ruff passed; maintained typing covered 95 sources and strict typing 35 |
| `make format-check` | Passed for 231 Python files |
| `make frontend-check` | Passed console typing, build and 326 tests, plus P2 source/test typing, build and 64 tests |
| Documentation and diagrams | All 95 documents passed and six project Mermaid diagrams parsed; the invalid syntax fixture was rejected |

Root commands were also tested with temporary failing P2 test and type files. Both
failed as required, and both files were removed before final validation. The
expanded Python discovery negative fixture covers P2 and P3 failure propagation.
Offline frozen installs included both development-only members, without external
version upgrades.

Both Dockerfiles rebuilt. Eight default transport, authentication and M1
(confirmed-investigation intake) checks passed with the original M1 identity and
ten audio frames. An owned nonroot, network-disabled serving-image probe imported
P1 and confirmed that the P2 and P3 development packages were absent. This smoke
does not qualify either new product.

Evidence is retained under
`.local/validation/p2-p3-foundation/8c0eedd87dc746f5b56d02c3c01becc0`. The complete
project acceptance catalogs still contain 17 planned, unregistered rows each. No
paid inference, new business database migration or remote continuous integration
(CI) ran. Previous P1 release artifacts remain intact; these new checks are
separate.

### Completion and next slice

This completes P2-I01/I02 only. Phase P2-A remains open for verified association,
durable inbox/idempotency and the standalone example before its phase exit.

The next bounded slice is P2-I03's fake-carrier verification and versioned seeded
association lifecycle. Its authentication/challenge and protected access tests
must precede durable inbox acceptance. Contract fixtures alone do not establish
those controls, concurrent idempotency, actual carrier delivery or browser media.
