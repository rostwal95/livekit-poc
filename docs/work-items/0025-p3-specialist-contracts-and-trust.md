# P3 specialist contracts and local trust boundary

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Implement P3-I03/I04 after the reviewed P3-A baseline. This slice provides strict
Python/TypeScript request, result and error codecs, a real TypeScript request
producer consumed by installed Python, trusted local service grants, immutable
scoped evidence and bounded live-attempt permits. It contributes contract/trust
assertions to P3-01/P3-03/P3-11; no complete product row is registered.

Only booking.evaluate_policy is supported. Document extraction, model clients,
HTTP endpoints, coordinator acceptance, database state, durable retries, callback
recovery and actual media remain planned. A wire-valid candidate is not accepted
work, a current case decision or mutation permission.

| Criterion | Given / When | Safety | Useful progress and evidence |
| --- | --- | --- | --- |
| Cross-language contract | Real TypeScript producer emits the fixed Unicode request; Python consumes installed package | Exact canonical bytes/fingerprint; duplicate keys, invalid UTF-8, unsupported versions and malformed values fail | Both producers match one frozen fixture; valid result/error round trips |
| Identity | Same delegation retries under a new attempt or changes bound semantics | Attempt metadata alone preserves logical fingerprint; scope/case/revision/evidence/context/deadline/route changes conflict | A distinct logical delegation and exact current attempt still match |
| Local trust | Separately configured service grants invoke/result/cancel/evidence access | No body principal, provider text or token supplies business mutation authority; wrong scope/operation/header fails | Authorized scoped invocation/evidence and result/cancel inspection succeed |
| Evidence/factual checks | Swap a source/version or return valid JSON with incorrect known policy facts | Exact accepted source bytes/digest and rule required; uncertainty remains explicit | Correctly grounded current candidate progresses; no factual-generalization claim |
| Time/resources | Trusted caller supplies observed time; fill bounded live registry | Reported completion time cannot revive expiry; no queue/timer/retries; unknown/forged permit fails | Owned release frees capacity and a valid subsequent invocation progresses |

## Interfaces and ownership

Python source is contracts.py/security.py in the existing development-only P3
workspace member. TypeScript source is specialist-ts/src with no runtime dependency.
contracts/delegation/v1.json is data-only and shared by the actual implementations.
The Python native baseline remains unchanged. Root owns shared workspace/lock,
source-discovery, lint/type/build and documentation registration.

The version-1 request binds schema/input version, capability, trusted scope,
delegation/case/revision, immutable context, scoped evidence metadata, absolute
millisecond deadline and logical conversation destination. The fingerprint excludes
only itself and the attempt identity/number. New attempts require exact result
attempt correlation; a transport retry never grants a new logical business action.
Results retain source/rule references, uncertainty and bounded producer/model/config
provenance. No provenance or confidence field grants truth or authorization.

LocalTrust accepts bounded operator-created grant configuration containing token
SHA-256 digests, principal IDs and separate operation/capability/source allowlists
per scope. Bearer values are exactly 43 opaque ASCII characters after the exact
prefix; configuration must use strong randomly generated tokens in real use.
Tests use synthetic tokens only. Constant-sized digest comparisons do not log or
persist raw bearer values. No credentials are read from the environment or files.
The header is validated by trusted code; a scope/principal in request JSON is not
trusted. This is a local mechanism, not enterprise identity or credential rotation.

EvidenceRegistry owns a bounded immutable byte snapshot and exact source metadata.
Python bytes are immutable; TypeScript clones initial and returned byte buffers.
No arbitrary URL fetch or filesystem source resolution exists. Image metadata has
byte/dimension bounds; actual image decoding/extraction remains a later capability.
Known fixed-policy evaluation distinguishes schema validity, source binding and
factual agreement. The case authority must still revalidate current revision and
exact consent atomically before any action.

AttemptBoundary is an ephemeral admission/observation registry, not acceptance or
execution ownership. Acquire requires current service authorization, a valid
remaining deadline and scoped evidence. Result/cancel inspection requires its
separate grant and known exact live attempt. Only the original minted permit can
release its slot. Active same-delegation changed payloads conflict. Python map operations use a
small process-local lock with no external work inside; JavaScript methods are
synchronous. No startup background task, timer, acknowledgement queue, durable
store or retry scheduler exists. Released history remains P1's responsibility. P1 remains the only future execution owner.

## Failure cases and validation

| Bound | Configuration / meaning |
| --- | --- |
| JSON bodies | Request 16,384 bytes; result 8,192; error 512; strict UTF-8, duplicate-free exact fields |
| JSON structure | Depth at most 12 containers; at most 256 value nodes; no fractions, exponents, negative zero or unsafe integers; bounded canonical copy rejects cycles/hooks/amplification |
| Context | Note at most 1,024 UTF-8 bytes; case revision 1–1,000,000; days 0–3,650 |
| Evidence | 1–4 request/result references; JSON source at most 4,096 bytes; encoded source at most 2 MiB and image dimensions at most 2,048 each |
| Source registry | At most 32 records and 8 MiB total bytes; no source fetching or decode tasks |
| Trust configuration | At most 32 principals, 16 scopes each, 64 source IDs per scope; aggregate canonical structure/body bounds also apply |
| Time | Safe integer UTC milliseconds through 2100; trusted observed admission time requires 1–60,000 ms remaining; reported completion timestamp is diagnostic |
| Live attempts | Default 4 total and 2 per principal; configurable maximum 16, no waiting queue; caller owns explicit release |

Shared fixtures separate parser failures from result matching and factual failures.
Tests include Unicode exact limits, late identifier line terminators, malformed
JSON/numerics, altered semantics, forged body principal, source replacement,
wrong account/attempt, ignored embedded instructions, wrong known facts/rules,
expired observed time, missing operation grant, malformed inspection operation,
unknown/forged permit, capacity and useful valid progression. Typed Python encoder
regressions prove malicious deepcopy is never called before size/type rejection.
No native SDK lifecycle is mocked or changed by this contract slice.

| Gate | Exact lane | Completion requirement |
| --- | --- | --- |
| G-CONTRACT | Python unittest and TypeScript Vitest shared fixtures; actual TypeScript producer passed via stdin to workspace-installed Python in isolated-interpreter mode | Same canonical bytes and fixed safe codes; structural success separately fails incorrect factual fixtures |
| G-FAST | Ruff/format and strict mypy for Python; strict TypeScript source/test checks and build | Nonzero new tests and root discovery required; no skipped/missing lane passes |
| G-OBS | Fixed ContractError codes and exact error envelope | No raw note, evidence bytes, tokens, provider message or arbitrary detail in public error |
| G-DURABLE/G-MEDIA | Not claimed in this slice | Future actual store/process/media gates remain open |
| G-PACKAGE | Workspace installed consumer only | Standalone wheel/npm archive qualification remains P3-I15 |

Existing focused commands run from the repository root:

```sh
.venv/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_specialist_contracts.py' -v
.venv/bin/mypy --strict projects/delegation-reliability/python/src/delegation_reliability/contracts.py projects/delegation-reliability/python/src/delegation_reliability/security.py
corepack pnpm --filter @livekit-ecosystem/delegation-specialist typecheck
corepack pnpm --filter @livekit-ecosystem/delegation-specialist test
corepack pnpm --filter @livekit-ecosystem/delegation-specialist build
```

Use the pinned Node/pnpm environment documented at the root. The producer/consumer
test uses the installed root Python environment with isolated imports and finite
subprocess budget; no repository PYTHONPATH or paid provider credentials are used.

## Results and handoff

Focused validation passed 39 Python tests: 18 unchanged native-baseline tests and
21 contract/trust tests, with zero skips. TypeScript passed 42 tests, including
actual producer output consumed by workspace-installed Python under -I. Ruff, formatting,
strict mypy on all seven Python source modules, strict TypeScript source/test
checks and the TypeScript build passed. Shared fixture has 28 named invalid rows
across parse, match and factual lanes; counts are observations, not pass thresholds.

Independent read-only review identified and corrected typed-dataclass deepcopy
before bounds, early Unicode length checks, malformed inspection-operation access,
large header slicing and exact byte-length/config primitive validation. Regression
tests cover those findings. A barrier-controlled eight-thread test verifies Python
admission cannot exceed its cap; an admitted second principal and post-release work
still progress. Final shared gates and independent automated review passed,
completing P3-I03/I04. make check passed 1,162 offline Python tests with zero
skips, lint and maintained/strict typing. make frontend-check passed 504 tests,
strict source/test checks, formatting and builds. All 99 documents passed; six
project Mermaid diagrams parsed and the malformed fixture was rejected.

The final npm-pack smoke installed the built TypeScript archive in a fresh consumer
outside the checkout and passed strict typing plus request decoding. The Python
parity lane uses a workspace-installed isolated interpreter; no built Python wheel
consumer is claimed. Full P3-I15 package qualification remains open. No HTTP
endpoint, durable acceptance or complete P3 product case is certified here.

The retained evidence/source inventory is under .local/validation/p2-p3-intake-contracts/0a88373e034e4ef8b2dca5fb8d4a7eb5,
shared with the [P2 intake handoff](0026-p2-postgres-inbox.md). AI assistance
implemented and independently reviewed this slice; human review and real-model
quality are not manufactured.

The next bounded task is P3-I05's authenticated read-only handler/client, using
these trust/resource checks for one P1-owned attempt. Complete its real boundary
tests before introducing coordinator durability. Breaking protocol changes require
an explicit version and coordinated producer/consumer fixtures; adding document
extraction must not silently reinterpret this first-capability contract.
